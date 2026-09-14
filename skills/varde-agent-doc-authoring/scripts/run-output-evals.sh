#!/usr/bin/env bash
#
# Run a skill's output-quality eval set (agentskills.io "evaluating skills"
# method): each test case is executed WITH the skill and WITHOUT it (baseline),
# each assertion is graded PASS/FAIL by an LLM judge, and per-config pass rate /
# tokens / time are aggregated into benchmark.json.
#
# This is the output-quality counterpart to run-evals.sh (which measures
# description TRIGGERING). Use this once a skill has stabilized and you want to
# know whether it actually improves the agent's output versus no skill at all.
#
# Usage:
#   scripts/run-output-evals.sh <skill-dir> [options]
#   scripts/run-output-evals.sh varde-spec
#   scripts/run-output-evals.sh varde-review-fix --runs 3 --iteration 2
#
# Options:
#   --runs N          runs per config per eval (default 1; >1 makes stddev meaningful)
#   --iteration N     iteration label for the workspace subdir (default 1)
#   --workspace DIR   output root (default <skill-dir>-workspace)
#   --sandbox-dir DIR working dir each run executes in (default: a fresh mktemp
#                     per run). Pass a disposable git clone/worktree for skills
#                     that mutate repo state (commits, file deletion) so the real
#                     tree is never touched.
#   --no-baseline     skip the without-skill run (with-skill only; no delta)
#
# <skill-dir> must contain SKILL.md and evals/evals.json in the schema:
#   { "skill_name": "...", "evals": [ { "id", "prompt",
#       "expected_output", "files"?: [...], "assertions"?: [...] } ] }
# A `files` entry is a path relative to <skill-dir>, copied into the sandbox
# before the run. A case with no `assertions` is executed (transcript + timing
# captured) but contributes no pass rate — matching the method's "add assertions
# after the first round of outputs" step.
#
# Output tree (mirrors the reference doc's layout):
#   <workspace>/iteration-<N>/eval-<id>/{with_skill,without_skill}/run-<k>/
#       transcript.txt   the run's final assistant text (graded artifact)
#       raw.json         full `claude -p` json envelope
#       timing.json      { duration_ms, tokens }
#       grading.json     { total, passed, results: [ {assertion, verdict, evidence} ] }
#   <workspace>/iteration-<N>/benchmark.json   aggregated per-config stats + delta
#
# Grading is LLM-judge only (claude -p): the judge sees expected_output, the
# assertions, and the transcript, and returns PASS/FAIL + evidence per assertion.
# For mechanically-checkable assertions a verification script is more reliable —
# see references/evaluating-skills.md; this runner does not shell out to one.
#
# Exit codes:
#   0  ran to completion (inspect benchmark.json for the with/without delta —
#      a nonzero pass count is NOT a gate here; this measures, it doesn't assert)
#   2  usage error or missing dependency (jq / claude)
#
# NOTE: this spawns roughly evals x configs x runs x 2 (run + judge) `claude -p`
# invocations — it is billed and slow. Start with 2-3 evals and --runs 1.

set -euo pipefail

die() { printf 'error: %s\n' "$1" >&2; exit 2; }
log() { printf '%s\n' "$1" >&2; }

case "${1:-}" in
  -h|--help|"")
    sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'
    exit 0
    ;;
esac

SKILL_DIR="${1%/}"; shift
RUNS=1
ITERATION=1
WORKSPACE=""
SANDBOX_DIR=""
BASELINE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --runs)       RUNS="${2:?--runs needs a value}"; shift 2 ;;
    --iteration)  ITERATION="${2:?--iteration needs a value}"; shift 2 ;;
    --workspace)  WORKSPACE="${2:?--workspace needs a value}"; shift 2 ;;
    --sandbox-dir) SANDBOX_DIR="${2:?--sandbox-dir needs a value}"; shift 2 ;;
    --no-baseline) BASELINE=0; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -d "$SKILL_DIR" ]              || die "skill dir not found: $SKILL_DIR"
[ -f "$SKILL_DIR/SKILL.md" ]     || die "no SKILL.md in $SKILL_DIR"
QUERIES="$SKILL_DIR/evals/evals.json"
[ -f "$QUERIES" ]                || die "no eval set at $QUERIES"
command -v jq >/dev/null 2>&1     || die "jq is required"
command -v claude >/dev/null 2>&1 || die "claude CLI is required"

SKILL_MD_ABS="$(cd "$SKILL_DIR" && pwd)/SKILL.md"
[ -n "$WORKSPACE" ] || WORKSPACE="${SKILL_DIR}-workspace"
ITER_DIR="$WORKSPACE/iteration-$ITERATION"
mkdir -p "$ITER_DIR"

len=$(jq '.evals | length' "$QUERIES") || die "invalid JSON in $QUERIES"
[ "$len" -gt 0 ] || die "no evals in $QUERIES"

# configs to run
configs="with_skill"
[ "$BASELINE" -eq 1 ] && configs="with_skill without_skill"

# aggregation accumulator: "config passrate tokens seconds" per graded run
ACC="$(mktemp)"
trap 'rm -f "$ACC"' EXIT

# Pull the final assistant text out of a `claude -p --output-format json` envelope.
extract_text() { jq -r '(.result // ([.messages[]?.content[]? | select(.type=="text") | .text] | join("\n")))' 2>/dev/null; }

for i in $(seq 0 $((len - 1))); do
  ev=$(jq ".evals[$i]" "$QUERIES")
  id=$(printf '%s' "$ev" | jq -r '.id // (input_line_number)')
  prompt=$(printf '%s' "$ev" | jq -r '.prompt')
  expected=$(printf '%s' "$ev" | jq -r '.expected_output // ""')
  nassert=$(printf '%s' "$ev" | jq '(.assertions // []) | length')
  files=()
  while IFS= read -r f; do [ -n "$f" ] && files+=("$f"); done \
    < <(printf '%s' "$ev" | jq -r '(.files // [])[]')
  eval_dir="$ITER_DIR/eval-$id"
  log "── eval $id ($((i+1))/$len): ${prompt:0:70}"

  for cfg in $configs; do
    for k in $(seq 1 "$RUNS"); do
      run_dir="$eval_dir/$cfg/run-$k"
      mkdir -p "$run_dir/outputs"

      # sandbox the run so real repo state is never mutated
      if [ -n "$SANDBOX_DIR" ]; then sbox="$SANDBOX_DIR"; else sbox="$(mktemp -d)"; fi
      skill_sbox="$sbox/skill"
      rm -rf "$skill_sbox"
      cp -R "$SKILL_DIR" "$skill_sbox"
      for f in ${files[@]+"${files[@]}"}; do
        [ -n "$f" ] || continue
        mkdir -p "$sbox/$(dirname "$f")"
        cp "$SKILL_DIR/$f" "$sbox/$f" 2>/dev/null || log "  warn: missing input file $f"
      done

      if [ "$cfg" = with_skill ]; then
        full="You have a skill available. First read and follow the instructions in $skill_sbox/SKILL.md, then handle this request:

$prompt"
      else
        full="$prompt"
      fi

      log "  $cfg run $k/${RUNS}…"
      start=$SECONDS
      ( cd "$sbox" && claude -p "$full" --output-format json ) > "$run_dir/raw.json" 2>/dev/null \
        || log "  warn: claude run exited nonzero (see raw.json)"
      dur=$(( (SECONDS - start) * 1000 ))

      extract_text < "$run_dir/raw.json" > "$run_dir/outputs/transcript.txt" || true
      cp "$run_dir/outputs/transcript.txt" "$run_dir/transcript.txt" 2>/dev/null || true
      tokens=$(jq -r '((.usage.input_tokens // 0) + (.usage.output_tokens // 0)) // 0' "$run_dir/raw.json" 2>/dev/null || echo 0)
      dur_json=$(jq -r '.duration_ms // empty' "$run_dir/raw.json" 2>/dev/null || true)
      [ -n "$dur_json" ] && dur="$dur_json"
      jq -n --argjson d "$dur" --argjson t "${tokens:-0}" \
        '{duration_ms:$d, tokens:$t}' > "$run_dir/timing.json"

      # grade (LLM judge) only when the case carries assertions
      if [ "$nassert" -gt 0 ]; then
        transcript=$(cat "$run_dir/outputs/transcript.txt")
        assertions_json=$(printf '%s' "$ev" | jq '.assertions')
        judge_prompt="You are grading an agent's output against a list of assertions. For EACH assertion, decide PASS or FAIL and cite concrete evidence quoted or referenced from the output — do not give the benefit of the doubt (a vague gesture at a requirement is a FAIL). Output ONLY a JSON object, no prose and no markdown fences, shaped exactly:
{\"results\":[{\"assertion\":\"<verbatim>\",\"verdict\":\"PASS\"|\"FAIL\",\"evidence\":\"<quote/ref>\"}]}

EXPECTED OUTPUT (what success looks like):
$expected

ASSERTIONS (grade each):
$assertions_json

AGENT OUTPUT (transcript to grade):
$transcript"
        judge_raw=$(claude -p "$judge_prompt" --output-format json 2>/dev/null || true)
        judged=$(printf '%s' "$judge_raw" | extract_text \
          | sed -e 's/^```json//' -e 's/^```//' -e 's/```$//' \
          | jq -c 'if type=="object" then . else {} end' 2>/dev/null || echo '{}')
        passed=$(printf '%s' "$judged" | jq '[.results[]? | select(.verdict=="PASS")] | length' 2>/dev/null || echo 0)
        total=$(printf '%s' "$judged" | jq '(.results // []) | length' 2>/dev/null || echo 0)
        [ "$total" -gt 0 ] || { total="$nassert"; log "  warn: judge output unparseable; counted 0/$nassert"; }
        jq -n --argjson total "$total" --argjson passed "${passed:-0}" \
          --argjson results "$(printf '%s' "$judged" | jq '.results // []')" \
          '{total:$total, passed:$passed, results:$results}' > "$run_dir/grading.json"
        rate=$(awk -v p="${passed:-0}" -v t="$total" 'BEGIN{printf (t>0)?"%.4f":"0", (t>0)?p/t:0}')
        printf '%s %s %s %s\n' "$cfg" "$rate" "${tokens:-0}" "$((dur/1000))" >> "$ACC"
        log "  → $cfg: ${passed:-0}/$total assertions"
      else
        jq -n '{total:0, passed:0, results:[], note:"no assertions yet — add after reviewing this run"}' > "$run_dir/grading.json"
        log "  → $cfg: no assertions (transcript + timing only)"
      fi

      [ -n "$SANDBOX_DIR" ] || rm -rf "$sbox"
    done
  done
done

# aggregate per config: mean+stddev pass_rate, mean tokens, mean seconds
agg() { # $1 = config; emits a jq object or "null"
  awk -v cfg="$1" '
    $1==cfg { n++; sr+=$2; sr2+=$2*$2; tok+=$3; sec+=$4 }
    END {
      if (n==0) { print "null"; exit }
      mean=sr/n; var=(sr2/n)-(mean*mean); if (var<0) var=0;
      printf "{\"pass_rate\":{\"mean\":%.4f,\"stddev\":%.4f},\"tokens\":{\"mean\":%.1f},\"time_seconds\":{\"mean\":%.1f},\"runs\":%d}", mean, sqrt(var), tok/n, sec/n, n
    }' "$ACC"
}
with=$(agg with_skill)
without=$(agg without_skill)
delta='null'
if [ "$with" != null ] && [ "$without" != null ]; then
  delta=$(jq -n --argjson w "$with" --argjson o "$without" \
    '{pass_rate:(($w.pass_rate.mean)-($o.pass_rate.mean)), tokens:(($w.tokens.mean)-($o.tokens.mean)), time_seconds:(($w.time_seconds.mean)-($o.time_seconds.mean))}')
fi
jq -n --arg skill "$SKILL_DIR" --argjson iter "$ITERATION" \
  --argjson with "$with" --argjson without "$without" --argjson delta "$delta" \
  '{skill:$skill, iteration:$iter, run_summary:{with_skill:$with, without_skill:$without, delta:$delta}}' \
  > "$ITER_DIR/benchmark.json"

log ""
log "benchmark → $ITER_DIR/benchmark.json"
jq '.run_summary' "$ITER_DIR/benchmark.json" >&2
