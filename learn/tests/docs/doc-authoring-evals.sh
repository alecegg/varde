#!/usr/bin/env bash
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
SKILL_DIR="$(skill_dir varde-doc-authoring)"
EVALS="$SKILL_DIR/evals/evals.json"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/doc-authoring-evals.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

jq -e '.skill_name == "varde-doc-authoring" and (.evals | type == "array")' \
  "$EVALS" >/dev/null || fail "evals.json is invalid"
jq -e 'type == "array" and length > 0 and all(.[]; (.query | type == "string") and (.should_trigger | type == "boolean"))' \
  "$SKILL_DIR/evals/trigger-queries.json" >/dev/null || fail "trigger-queries.json is invalid"

while IFS= read -r fixture; do
  [ -f "$SKILL_DIR/$fixture" ] || fail "declared fixture is missing: $fixture"
done < <(jq -r '.evals[].files[]?' "$EVALS")

while IFS= read -r script; do
  [ -f "$SKILL_DIR/$script" ] || fail "declared script is missing: $script"
done < <(jq -r '.evals[] | .setup_script?, .verification_script? | select(. != null)' "$EVALS")

check_declared_assertion() {
  local eval_id="$1" result_file="$2" declared
  declared="$(jq -c --arg id "$eval_id" '.evals[] | select((.id | tostring) == $id) | .assertions' "$EVALS")"
  jq -e --argjson declared "$declared" \
    '.results | all(.[]; .assertion as $a | ($declared | index($a)) != null)' \
    "$result_file" >/dev/null || fail "verifier result contains an undeclared assertion for eval $eval_id"
}

# Smoke-test the review verifier's declared-assertion contract on valid artifacts.
verifier="$SKILL_DIR/evals/verify-review-branches.sh"
setup="$SKILL_DIR/evals/setup-agent-review.sh"
fixture="evals/fixtures/review-guidance/AGENTS.md"

fixed="$TEST_ROOT/fixed"
mkdir -p "$fixed/$(dirname "$fixture")"
awk '!(/^- Include the release date from the source notes\.$/ && seen++)' \
  "$SKILL_DIR/$fixture" > "$fixed/$fixture"
EVAL_ID=4 EVAL_SANDBOX_DIR="$fixed" EVAL_SKILL_DIR="$SKILL_DIR" bash "$verifier" > "$TEST_ROOT/fixed.json"
jq -e '.results[0].verdict == "PASS"' "$TEST_ROOT/fixed.json" >/dev/null \
  || fail "review verifier rejects a single-copy duplicate removal"
check_declared_assertion 4 "$TEST_ROOT/fixed.json"

report_only="$TEST_ROOT/report-only"
run_dir="$TEST_ROOT/run"
mkdir -p "$report_only/$(dirname "$fixture")" "$run_dir"
cp "$SKILL_DIR/$fixture" "$report_only/$fixture"
EVAL_SANDBOX_DIR="$report_only" EVAL_RUN_DIR="$run_dir" bash "$setup"
EVAL_ID=5 EVAL_SANDBOX_DIR="$report_only" EVAL_RUN_DIR="$run_dir" EVAL_SKILL_DIR="$SKILL_DIR" \
  bash "$verifier" > "$TEST_ROOT/report-only.json"
jq -e 'all(.results[]; .verdict == "PASS")' "$TEST_ROOT/report-only.json" >/dev/null \
  || fail "review verifier rejects an unchanged report-only target"
check_declared_assertion 5 "$TEST_ROOT/report-only.json"

printf '%s\n' '# Review report' > "$report_only/review.md"
EVAL_ID=5 EVAL_SANDBOX_DIR="$report_only" EVAL_RUN_DIR="$run_dir" EVAL_SKILL_DIR="$SKILL_DIR" \
  bash "$verifier" > "$TEST_ROOT/report-written.json"
jq -e '.results[1].verdict == "FAIL"' "$TEST_ROOT/report-written.json" >/dev/null \
  || fail "review verifier accepts a Markdown report from an agent-initiated review"

echo "PASS: doc authoring eval fixtures and review verifiers"
