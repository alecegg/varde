#!/usr/bin/env bash
#
# Run a skill's output-quality eval set (agentskills.io "evaluating skills"
# method): each test case is executed WITH the skill and WITHOUT it (baseline),
# each assertion is graded PASS/FAIL by an LLM judge, and per-config pass rate /
# tokens / time / successful-assertion efficiency are aggregated into benchmark.json.
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
#   --eval ID         run only this evaluation ID (repeatable)
#   --timeout-seconds N
#                     maximum seconds per Claude invocation (default 300)
#   --sandbox-dir DIR template copied into a fresh working directory for each
#                     run. Pass a disposable standalone clone for skills that
#                     need repository state. Linked worktrees are rejected.
#   --no-baseline     skip the without-skill run (with-skill only; no delta)
#
# <skill-dir> must contain SKILL.md and evals/evals.json in the schema:
#   { "skill_name": "...", "evals": [ { "id", "prompt",
#       "expected_output", "files"?: [...], "assertions"?: [],
#       "setup_script"?: "evals/...", "verification_script"?: "evals/..." } ] }
# A `files` entry is a path relative to <skill-dir>, copied into the sandbox
# before the run. `setup_script` prepares the sandbox before the agent runs.
# `verification_script` emits deterministic assertion results after the run;
# the LLM judge receives only remaining assertions. Script paths stay relative
# to <skill-dir>. A case without assertions contributes no pass rate.
#
# Output tree (mirrors the reference doc's layout):
#   <workspace>/iteration-<N>/eval-<id>/{with_skill,without_skill}/run-<k>/
#       transcript.txt   the run's final assistant text (graded artifact)
#       raw.json         full `claude -p` json envelope
#       timing.json      duration, complete token usage, and evaluated-agent cost
#       verification.json deterministic results, when configured
#       judge-raw.json   full judge envelope, when judging remains necessary
#       judge-grading.json parsed judge results
#       grading.json     { total, passed, results: [ {assertion, verdict, evidence} ] }
#   <workspace>/iteration-<N>/benchmark.json   aggregated per-config stats + delta
#
# Deterministic verification runs first. The LLM judge sees only assertions the
# verifier did not grade. Both sources return PASS/FAIL with concrete evidence.
#
# Exit codes:
#   0  ran to completion (inspect benchmark.json for the with/without delta —
#      a nonzero pass count is NOT a gate here; this measures, it doesn't assert)
#   2  usage error or missing dependency (jq / claude / perl)
#
# NOTE: this spawns roughly evals x configs x runs x 2 (run + judge) `claude -p`
# invocations — it is billed and slow. Start with 2-3 evals and --runs 1.

set -euo pipefail

die() { printf 'error: %s\n' "$1" >&2; exit 2; }
log() { printf '%s\n' "$1" >&2; }

validate_eval_script() {
  local rel="$1" label="$2"
  [ -n "$rel" ] || return 0
  case "$rel" in
    /*|..|../*|*/..|*/../*) die "$label must stay inside the skill directory: $rel" ;;
  esac
  [ -f "$SKILL_DIR/$rel" ] || die "$label not found: $SKILL_DIR/$rel"
}

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
EVAL_IDS=()
RUN_TIMEOUT_SECONDS=300
while [ $# -gt 0 ]; do
  case "$1" in
    --runs)       RUNS="${2:?--runs needs a value}"; shift 2 ;;
    --iteration)  ITERATION="${2:?--iteration needs a value}"; shift 2 ;;
    --workspace)  WORKSPACE="${2:?--workspace needs a value}"; shift 2 ;;
    --eval)       EVAL_IDS+=("${2:?--eval needs a value}"); shift 2 ;;
    --timeout-seconds) RUN_TIMEOUT_SECONDS="${2:?--timeout-seconds needs a value}"; shift 2 ;;
    --sandbox-dir) SANDBOX_DIR="${2:?--sandbox-dir needs a value}"; shift 2 ;;
    --no-baseline) BASELINE=0; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -d "$SKILL_DIR" ]              || die "skill dir not found: $SKILL_DIR"
SKILL_DIR="$(cd "$SKILL_DIR" && pwd)"
[ -f "$SKILL_DIR/SKILL.md" ]     || die "no SKILL.md in $SKILL_DIR"
QUERIES="$SKILL_DIR/evals/evals.json"
[ -f "$QUERIES" ]                || die "no eval set at $QUERIES"
command -v jq >/dev/null 2>&1     || die "jq is required"
command -v claude >/dev/null 2>&1 || die "claude CLI is required"
command -v perl >/dev/null 2>&1   || die "perl is required"
case "$RUN_TIMEOUT_SECONDS" in
  ''|*[!0-9]*) die "--timeout-seconds must be a positive integer" ;;
esac
[ "$RUN_TIMEOUT_SECONDS" -gt 0 ] || die "--timeout-seconds must be a positive integer"
[ -z "$SANDBOX_DIR" ] || [ -d "$SANDBOX_DIR" ] || die "sandbox dir not found: $SANDBOX_DIR"
[ -z "$SANDBOX_DIR" ] || [ ! -f "$SANDBOX_DIR/.git" ] || \
  die "--sandbox-dir must be a standalone clone or directory, not a linked worktree"

[ -n "$WORKSPACE" ] || WORKSPACE="${SKILL_DIR}-workspace"
ITER_DIR="$WORKSPACE/iteration-$ITERATION"
mkdir -p "$ITER_DIR"

len=$(jq '.evals | length' "$QUERIES") || die "invalid JSON in $QUERIES"
[ "$len" -gt 0 ] || die "no evals in $QUERIES"
for selected_id in ${EVAL_IDS[@]+"${EVAL_IDS[@]}"}; do
  jq -e --arg id "$selected_id" '.evals | any((.id | tostring) == $id)' \
    "$QUERIES" >/dev/null || die "evaluation not found: $selected_id"
done

eval_selected() {
  local id="$1" selected_id
  [ "${#EVAL_IDS[@]}" -eq 0 ] && return 0
  for selected_id in "${EVAL_IDS[@]}"; do
    [ "$selected_id" = "$id" ] && return 0
  done
  return 1
}

# configs to run
configs="with_skill"
[ "$BASELINE" -eq 1 ] && configs="with_skill without_skill"

# Aggregation accumulator fields per graded run:
# "config passrate token-status tokens seconds passed-assertions"
ACC="$(mktemp)"
trap 'rm -f "$ACC"' EXIT

# Pull the final assistant text out of a `claude -p --output-format json` envelope.
extract_text() { jq -r '(.result // ([.messages[]?.content[]? | select(.type=="text") | .text] | join("\n")))' 2>/dev/null; }

run_claude_with_timeout() {
  perl -MPOSIX=:sys_wait_h,setsid -MTime::HiRes=time,sleep -e '
    my $seconds = shift @ARGV;
    pipe(my $ready_read, my $ready_write) or die "pipe failed: $!";
    my $child = fork();
    defined $child or die "fork failed: $!";
    if ($child == 0) {
      close $ready_read;
      setsid() >= 0 or die "setsid failed: $!";
      syswrite($ready_write, "1") == 1 or die "ready write failed: $!";
      close $ready_write;
      exec @ARGV or die "exec failed: $!";
    }
    close $ready_write;
    sysread($ready_read, my $ready, 1) == 1 or die "child setup failed";
    close $ready_read;

    my $status;
    my $reaped = 0;
    my $terminate_group = sub {
      my ($signal) = @_;
      kill $signal, -$child;
    };
    for my $signal (qw(INT TERM HUP)) {
      $SIG{$signal} = sub {
        $terminate_group->("KILL");
        waitpid($child, 0);
        exit 128 + ($signal eq "INT" ? 2 : $signal eq "HUP" ? 1 : 15);
      };
    }

    my $deadline = time() + $seconds;
    while (time() < $deadline) {
      my $result = waitpid($child, WNOHANG);
      if ($result == $child) {
        $status = $?;
        $reaped = 1;
        last;
      }
      sleep 0.02;
    }

    if (!$reaped) {
      $terminate_group->("TERM");
      my $grace_deadline = time() + 0.25;
      while (time() < $grace_deadline) {
        my $result = waitpid($child, WNOHANG);
        if ($result == $child) {
          $status = $?;
          $reaped = 1;
        }
        last unless kill 0, -$child;
        sleep 0.02;
      }
      $terminate_group->("KILL") if kill 0, -$child;
      if (!$reaped) {
        waitpid($child, 0);
        $status = $?;
      }
      sleep 0.02 while kill 0, -$child;
      exit 142;
    }

    exit(($status & 127) ? 128 + ($status & 127) : $status >> 8);
  ' "$RUN_TIMEOUT_SECONDS" "$@"
}

record_run_timing() {
  local raw_json="$run_dir/raw.json"
  local usage_json cost_json duration_json

  token_status=$(jq -r '
    if (.usage | type) == "object" and
       (((.usage.input_tokens | type) == "number") or
        ((.usage.output_tokens | type) == "number") or
        ((.usage.cache_creation_input_tokens | type) == "number") or
        ((.usage.cache_read_input_tokens | type) == "number"))
    then "measured" else "unavailable" end
  ' "$raw_json" 2>/dev/null || echo unavailable)
  [ -n "$token_status" ] || token_status=unavailable
  tokens=$(jq -r \
    '[.usage.input_tokens?, .usage.output_tokens?,
      .usage.cache_creation_input_tokens?, .usage.cache_read_input_tokens?]
     | map(select(type == "number")) | add // 0' \
    "$raw_json" 2>/dev/null || echo 0)
  usage_json=$(jq -c '
    {
      input_tokens: (if (.usage.input_tokens? | type) == "number" then .usage.input_tokens else null end),
      output_tokens: (if (.usage.output_tokens? | type) == "number" then .usage.output_tokens else null end),
      cache_creation_input_tokens: (if (.usage.cache_creation_input_tokens? | type) == "number" then .usage.cache_creation_input_tokens else null end),
      cache_read_input_tokens: (if (.usage.cache_read_input_tokens? | type) == "number" then .usage.cache_read_input_tokens else null end)
    }
  ' "$raw_json" 2>/dev/null || echo '{}')
  [ -n "$usage_json" ] || usage_json='{}'
  cost_json=$(jq -r '
    if (.total_cost_usd | type) == "number" then .total_cost_usd else null end
  ' "$raw_json" 2>/dev/null || echo null)
  [ -n "$cost_json" ] || cost_json=null
  duration_json=$(jq -r '.duration_ms // empty' "$raw_json" 2>/dev/null || true)
  [ -z "$duration_json" ] || dur="$duration_json"

  if [ "$token_status" = measured ]; then
    jq -n --argjson d "$dur" --argjson t "${tokens:-0}" \
      --argjson usage "$usage_json" --argjson cost "$cost_json" \
      --arg outcome "$run_outcome" --argjson exit "$run_status" \
      --argjson timeout "$RUN_TIMEOUT_SECONDS" \
      '{duration_ms:$d, tokens:$t, usage:$usage, cost_usd:$cost,
        outcome:$outcome, exit_code:$exit, timeout_seconds:$timeout}' \
      > "$run_dir/timing.json"
  else
    jq -n --argjson d "$dur" --argjson usage "$usage_json" \
      --argjson cost "$cost_json" --arg outcome "$run_outcome" \
      --argjson exit "$run_status" --argjson timeout "$RUN_TIMEOUT_SECONDS" \
      '{duration_ms:$d, tokens:null, usage:$usage, cost_usd:$cost,
        outcome:$outcome, exit_code:$exit, timeout_seconds:$timeout}' \
      > "$run_dir/timing.json"
  fi
}

run_deterministic_verification() {
  local assertions_json="$1"
  local verified='{"results":[]}'

  if [ -n "$verification_script" ]; then
    ( cd "$sbox" && \
      EVAL_ID="$id" EVAL_CONFIG="$cfg" EVAL_RUN="$k" \
      EVAL_RUN_DIR="$run_dir_abs" \
      EVAL_TRANSCRIPT="$run_dir_abs/outputs/transcript.txt" \
      EVAL_SKILL_DIR="$eval_skill_dir" EVAL_SANDBOX_DIR="$sbox" \
      bash "$eval_skill_dir/$verification_script" ) \
      > "$run_dir/verification.json" \
      || die "verification_script failed for eval $id, $cfg run $k"
    verified=$(jq -c --argjson declared "$assertions_json" '
      if type != "object" or (.results | type) != "array" then
        error("verification result must contain a results array")
      elif any(.results[]?; (.assertion as $a | $declared | index($a)) == null) then
        error("verification result contains an undeclared assertion")
      elif ([.results[].assertion] | length) != ([.results[].assertion] | unique | length) then
        error("verification result contains duplicate assertions")
      elif any(.results[]?; (.verdict != "PASS" and .verdict != "FAIL")) then
        error("verification verdict must be PASS or FAIL")
      else . end
    ' "$run_dir/verification.json") \
      || die "invalid verification result for eval $id, $cfg run $k"
  else
    printf '%s\n' "$verified" > "$run_dir/verification.json"
  fi
  printf '%s\n' "$verified"
}

run_llm_judge() {
  local judge_assertions="$1" transcript="$2"
  local judge_prompt judge_raw judge_status

  judge_prompt="You are grading an agent's output against a list of assertions. For EACH assertion, decide PASS or FAIL and cite concrete evidence quoted or referenced from the output — do not give the benefit of the doubt (a vague gesture at a requirement is a FAIL). Output ONLY a JSON object, no prose and no markdown fences, shaped exactly:
{\"results\":[{\"assertion\":\"<verbatim>\",\"verdict\":\"PASS\"|\"FAIL\",\"evidence\":\"<quote/ref>\"}]}

EXPECTED OUTPUT (what success looks like):
$expected

ASSERTIONS (grade each):
$judge_assertions

AGENT OUTPUT (transcript to grade):
$transcript"
  judge_status=0
  if judge_raw=$(cd "$run_dir" && run_claude_with_timeout claude -p "$judge_prompt" \
    --output-format json --disable-slash-commands \
    --setting-sources local 2>/dev/null); then
    judge_outcome=completed
  else
    judge_status=$?
    if [ "$judge_status" -eq 142 ]; then
      judge_outcome=timed_out
      log "  warn: judge timed out after ${RUN_TIMEOUT_SECONDS}s"
    else
      judge_outcome=failed
      log "  warn: judge exited nonzero"
    fi
  fi
  printf '%s\n' "$judge_raw" > "$run_dir/judge-raw.json"
  judged=$(printf '%s' "$judge_raw" | extract_text \
    | sed -e 's/^```json//' -e 's/^```//' -e 's/```$//' \
    | jq -c 'if type=="object" then . else {} end' 2>/dev/null || echo '{}')
  [ -n "$judged" ] || judged='{}'
}

grade_current_run() {
  local assertions_json verified judge_assertions judged judge_grading
  local transcript merged passed total rate

  if [ "$nassert" -eq 0 ]; then
    jq -n --arg run_outcome "$run_outcome" \
      '{total:0, passed:0, results:[], run_outcome:$run_outcome,
        judge_outcome:"not_needed",
        note:"no assertions yet — add after reviewing this run"}' \
      > "$run_dir/grading.json"
    log "  → $cfg: no assertions (transcript + timing only)"
    return
  fi

  assertions_json=$(printf '%s' "$ev" | jq '.assertions')
  judge_outcome=not_run
  if [ "$run_outcome" = timed_out ]; then
    printf '%s\n' '{"results":[]}' > "$run_dir/verification.json"
    printf '%s\n' '{}' > "$run_dir/judge-raw.json"
    printf '%s\n' '{"results":[]}' > "$run_dir/judge-grading.json"
    merged=$(jq -cn --argjson declared "$assertions_json" \
      --arg timeout "$RUN_TIMEOUT_SECONDS" '
        {results: [$declared[] | {
          assertion:., verdict:"FAIL",
          evidence:("Evaluated run timed out after " + $timeout + " seconds")
        }]}
      ')
  else
    transcript=$(cat "$run_dir/outputs/transcript.txt")
    verified=$(run_deterministic_verification "$assertions_json")
    judge_assertions=$(jq -cn --argjson declared "$assertions_json" \
      --argjson verified "$verified" '
        $declared - [$verified.results[]?.assertion]
      ')
    judged='{"results":[]}'
    if [ "$(printf '%s' "$judge_assertions" | jq 'length')" -gt 0 ]; then
      run_llm_judge "$judge_assertions" "$transcript"
    else
      judge_outcome=not_needed
      printf '%s\n' '{}' > "$run_dir/judge-raw.json"
    fi
    judge_grading=$(printf '%s' "$judged" | jq -c \
      '{results:(.results // [])}' 2>/dev/null || echo '{"results":[]}')
    [ -n "$judge_grading" ] || judge_grading='{"results":[]}'
    printf '%s\n' "$judge_grading" > "$run_dir/judge-grading.json"
    merged=$(jq -cn --argjson declared "$assertions_json" \
      --argjson verified "$verified" --argjson judged "$judge_grading" '
        [$verified.results[]?, $judged.results[]?] as $all
        | {results: [$declared[] as $assertion
            | ([$all[] | select(.assertion == $assertion)] | first)
              // {assertion:$assertion, verdict:"FAIL", evidence:"No grading result returned"}]}
      ')
  fi

  passed=$(printf '%s' "$merged" | jq '[.results[] | select(.verdict=="PASS")] | length')
  total="$nassert"
  jq -n --argjson total "$total" --argjson passed "$passed" \
    --argjson results "$(printf '%s' "$merged" | jq '.results')" \
    --arg run_outcome "$run_outcome" --arg judge_outcome "$judge_outcome" \
    '{total:$total, passed:$passed, results:$results,
      run_outcome:$run_outcome, judge_outcome:$judge_outcome}' \
    > "$run_dir/grading.json"
  rate=$(awk -v p="${passed:-0}" -v t="$total" \
    'BEGIN{printf (t>0)?"%.4f":"0", (t>0)?p/t:0}')
  printf '%s %s %s %s %s %s %s %s\n' \
    "$cfg" "$rate" "$token_status" "${tokens:-0}" "$((dur/1000))" \
    "${passed:-0}" "$run_outcome" "$judge_outcome" >> "$ACC"
  log "  → $cfg: ${passed:-0}/$total assertions"
}

for i in $(seq 0 $((len - 1))); do
  ev=$(jq ".evals[$i]" "$QUERIES")
  id=$(printf '%s' "$ev" | jq -r '.id // (input_line_number)')
  eval_selected "$id" || continue
  prompt=$(printf '%s' "$ev" | jq -r '.prompt')
  expected=$(printf '%s' "$ev" | jq -r '.expected_output // ""')
  nassert=$(printf '%s' "$ev" | jq '(.assertions // []) | length')
  setup_script=$(printf '%s' "$ev" | jq -r '.setup_script // ""')
  verification_script=$(printf '%s' "$ev" | jq -r '.verification_script // ""')
  validate_eval_script "$setup_script" setup_script
  validate_eval_script "$verification_script" verification_script
  files=()
  while IFS= read -r f; do [ -n "$f" ] && files+=("$f"); done \
    < <(printf '%s' "$ev" | jq -r '(.files // [])[]')
  eval_dir="$ITER_DIR/eval-$id"
  log "── eval $id ($((i+1))/$len): ${prompt:0:70}"

  for cfg in $configs; do
    for k in $(seq 1 "$RUNS"); do
      run_dir="$eval_dir/$cfg/run-$k"
      mkdir -p "$run_dir/outputs"
      run_dir_abs="$(cd "$run_dir" && pwd)"

      # Every run gets a fresh sandbox. A supplied directory is a template.
      sbox="$(mktemp -d)"
      if [ -n "$SANDBOX_DIR" ]; then
        cp -R "$SANDBOX_DIR"/. "$sbox"/
      fi
      skill_sbox=""
      eval_skill_dir="$SKILL_DIR"
      if [ "$cfg" = with_skill ]; then
        skill_sbox="$sbox/.skill-under-evaluation"
        cp -R "$SKILL_DIR" "$skill_sbox"
        eval_skill_dir="$skill_sbox"
      fi
      for f in ${files[@]+"${files[@]}"}; do
        [ -n "$f" ] || continue
        mkdir -p "$sbox/$(dirname "$f")"
        cp "$SKILL_DIR/$f" "$sbox/$f" 2>/dev/null || log "  warn: missing input file $f"
      done
      if [ -n "$setup_script" ]; then
        ( cd "$sbox" && \
          EVAL_ID="$id" EVAL_CONFIG="$cfg" EVAL_RUN="$k" \
          EVAL_RUN_DIR="$run_dir_abs" EVAL_SKILL_DIR="$eval_skill_dir" \
          EVAL_SANDBOX_DIR="$sbox" bash "$eval_skill_dir/$setup_script" ) \
          > "$run_dir/setup.txt" 2>&1 \
          || die "setup_script failed for eval $id, $cfg run $k"
      fi

      if [ "$cfg" = with_skill ]; then
        full="Evaluate only the skill snapshot at $skill_sbox/SKILL.md.
Read it directly. Resolve every relative path from $skill_sbox.
Do not invoke or read an installed skill sharing its name.
Then handle this request:

$prompt"
      else
        full="$prompt"
      fi

      log "  $cfg run $k/${RUNS}…"
      start=$SECONDS
      claude_args=(
        --output-format json
        --disable-slash-commands
        --setting-sources "project,local"
        --permission-mode auto
      )
      if [ "$cfg" = with_skill ]; then
        claude_args+=(--add-dir "$skill_sbox")
      fi
      run_status=0
      if ( cd "$sbox" && run_claude_with_timeout claude -p "$full" "${claude_args[@]}" ) \
        > "$run_dir/raw.json" 2>/dev/null; then
        run_outcome=completed
      else
        run_status=$?
        if [ "$run_status" -eq 142 ]; then
          run_outcome=timed_out
          log "  warn: claude run timed out after ${RUN_TIMEOUT_SECONDS}s"
        else
          run_outcome=failed
          log "  warn: claude run exited nonzero (see raw.json)"
        fi
      fi
      dur=$(( (SECONDS - start) * 1000 ))

      extract_text < "$run_dir/raw.json" > "$run_dir/outputs/transcript.txt" || true
      cp "$run_dir/outputs/transcript.txt" "$run_dir/transcript.txt" 2>/dev/null || true
      record_run_timing
      grade_current_run

      rm -rf "$sbox"
    done
  done
done

# Aggregate per config. Efficiency uses only runs with measured token counts.
agg() { # $1 = config; emits a jq object or "null"
  awk -v cfg="$1" '
    $1==cfg {
      n++; sr+=$2; sr2+=$2*$2; sec+=$5; passed+=$6;
      if ($7=="completed") completed++;
      else if ($7=="failed") failed++;
      else if ($7=="timed_out") timed_out++;
      if ($8=="timed_out") judge_timed_out++;
      if ($3=="measured") { measured++; tok+=$4; measured_passed+=$6 }
      else { unavailable++ }
    }
    END {
      if (n==0) { print "null"; exit }
      mean=sr/n; var=(sr2/n)-(mean*mean); if (var<0) var=0;
      token_mean=(measured>0) ? sprintf("%.1f", tok/measured) : "null";
      token_total=(measured>0) ? sprintf("%.0f", tok) : "null";
      if (measured==0) { efficiency_status="unavailable"; efficiency="null" }
      else if (tok==0) { efficiency_status="zero_tokens"; efficiency="null" }
      else {
        efficiency_status=(unavailable>0) ? "partial" : "measured";
        efficiency=sprintf("%.4f", measured_passed*1000/tok)
      }
      printf "{\"pass_rate\":{\"mean\":%.4f,\"stddev\":%.4f},\"tokens\":{\"mean\":%s,\"total\":%s,\"measured_runs\":%d,\"unavailable_runs\":%d},\"time_seconds\":{\"mean\":%.1f},\"successful_assertions\":{\"total\":%d},\"token_efficiency\":{\"status\":\"%s\",\"successful_assertions_per_1000_tokens\":%s},\"outcomes\":{\"completed\":%d,\"failed\":%d,\"timed_out\":%d,\"judge_timed_out\":%d},\"runs\":%d}", mean, sqrt(var), token_mean, token_total, measured, unavailable, sec/n, passed, efficiency_status, efficiency, completed, failed, timed_out, judge_timed_out, n
    }' "$ACC"
}
with=$(agg with_skill)
without=$(agg without_skill)
delta='null'
if [ "$with" != null ] && [ "$without" != null ]; then
  delta=$(jq -n --argjson w "$with" --argjson o "$without" \
    '{
      pass_rate:(($w.pass_rate.mean)-($o.pass_rate.mean)),
      tokens:(if $w.tokens.mean != null and $o.tokens.mean != null then ($w.tokens.mean)-($o.tokens.mean) else null end),
      time_seconds:(($w.time_seconds.mean)-($o.time_seconds.mean)),
      successful_assertions:(($w.successful_assertions.total)-($o.successful_assertions.total)),
      successful_assertions_per_1000_tokens:(
        if $w.token_efficiency.successful_assertions_per_1000_tokens != null and
           $o.token_efficiency.successful_assertions_per_1000_tokens != null
        then ($w.token_efficiency.successful_assertions_per_1000_tokens)-($o.token_efficiency.successful_assertions_per_1000_tokens)
        else null end
      )
    }')
fi
jq -n --arg skill "$SKILL_DIR" --argjson iter "$ITERATION" \
  --argjson with "$with" --argjson without "$without" --argjson delta "$delta" \
  '{skill:$skill, iteration:$iter, run_summary:{with_skill:$with, without_skill:$without, delta:$delta}}' \
  > "$ITER_DIR/benchmark.json"

log ""
log "benchmark → $ITER_DIR/benchmark.json"
jq '.run_summary' "$ITER_DIR/benchmark.json" >&2
