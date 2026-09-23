#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPARATOR="$SKILLS_DIR/varde-change/scripts/compare-path-benchmarks.py"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

write_run() {
  local iteration="$1" eval_id="$2" run="$3" tokens="$4" passed="$5"
  local run_dir="$iteration/eval-$eval_id/with_skill/run-$run"
  mkdir -p "$run_dir"
  cat > "$run_dir/timing.json" <<JSON
{"duration_ms":1000,"usage":{"input_tokens":$tokens,"output_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}
JSON
  cat > "$run_dir/grading.json" <<JSON
{"total":2,"passed":$passed,"run_outcome":"completed","judge_outcome":"not_needed","results":[]}
JSON
  cat > "$run_dir/raw.json" <<JSON
{"num_turns":$run}
JSON
}

write_timeout() {
  local iteration="$1" eval_id="$2" run="$3"
  local run_dir="$iteration/eval-$eval_id/with_skill/run-$run"
  mkdir -p "$run_dir"
  printf '%s\n' '{"duration_ms":300000,"usage":{},"outcome":"timed_out"}' \
    > "$run_dir/timing.json"
  printf '%s\n' '{"total":2,"passed":0,"run_outcome":"timed_out","judge_outcome":"not_needed","results":[]}' \
    > "$run_dir/grading.json"
  : > "$run_dir/raw.json"
}

cat > "$TEST_ROOT/catalog.json" <<'JSON'
{
  "schema_version": 1,
  "routes": [
    {"id":"alpha","eval_id":1,"required_documents":[],"observed_documents":[]},
    {"id":"beta","eval_id":2,"required_documents":[],"observed_documents":[]}
  ]
}
JSON

write_run "$TEST_ROOT/baseline" 1 1 1000 1
write_run "$TEST_ROOT/baseline" 2 1 3000 2
write_timeout "$TEST_ROOT/baseline" 2 2
write_run "$TEST_ROOT/current" 1 1 500 2
write_run "$TEST_ROOT/current" 2 1 1500 2

python3 "$COMPARATOR" \
  --catalog "$TEST_ROOT/catalog.json" \
  --baseline "$TEST_ROOT/baseline" \
  --current "$TEST_ROOT/current" \
  --output "$TEST_ROOT/comparison.json"

jq -e '
  .schema_version == 1 and
  .routes.alpha.baseline.tokens.mean == 1000 and
  .routes.alpha.current.tokens.mean == 500 and
  .routes.alpha.delta.tokens_percent == -50 and
  .routes.alpha.current.assertions == {passed:2,total:2} and
  .routes.beta.current.workflow_cycles.mean == 1 and
  .routes.beta.baseline.tokens.measured_runs == 1 and
  .routes.beta.baseline.tokens.unavailable_runs == 1 and
  .routes.beta.baseline.outcomes.timed_out == 1 and
  .portfolio.baseline.tokens.total == 4000 and
  .portfolio.current.tokens.total == 2000 and
  .portfolio.delta.tokens_percent == null and
  .portfolio.delta.token_efficiency_percent == null and
  .portfolio.delta.usage_cohort_match == false and
  .portfolio.paired_measured.baseline.tokens.total == 4000 and
  .portfolio.paired_measured.current.tokens.total == 2000 and
  .portfolio.paired_measured.delta.tokens_percent == -50 and
  .portfolio.paired_measured.delta.token_efficiency_percent == 166.7 and
  .portfolio.paired_measured.delta.usage_cohort_match == true and
  .portfolio.delta.canonical_models_match == true
' "$TEST_ROOT/comparison.json" >/dev/null || fail "unexpected comparison output"

if python3 "$COMPARATOR" --catalog "$TEST_ROOT/catalog.json" \
  --baseline "$TEST_ROOT/missing" --current "$TEST_ROOT/current" \
  >/dev/null 2>&1; then
  fail "missing benchmark iterations should fail"
fi

write_timeout "$TEST_ROOT/timeouts-baseline" 1 1
write_timeout "$TEST_ROOT/timeouts-baseline" 2 1
write_timeout "$TEST_ROOT/timeouts-current" 1 1
write_timeout "$TEST_ROOT/timeouts-current" 2 1
python3 "$COMPARATOR" \
  --catalog "$TEST_ROOT/catalog.json" \
  --baseline "$TEST_ROOT/timeouts-baseline" \
  --current "$TEST_ROOT/timeouts-current" \
  --output "$TEST_ROOT/timeouts-comparison.json"
assert_json_expression='
  .portfolio.paired_measured.baseline.runs == 0 and
  .portfolio.paired_measured.baseline.tokens.mean == null and
  .portfolio.paired_measured.baseline.time_seconds.mean == null and
  .portfolio.paired_measured.baseline.workflow_cycles.mean == null and
  .portfolio.paired_measured.current.runs == 0 and
  .portfolio.paired_measured.delta.tokens_percent == null and
  .portfolio.paired_measured.delta.time_seconds_percent == null and
  .portfolio.paired_measured.delta.workflow_cycles_percent == null
'
jq -e "$assert_json_expression" "$TEST_ROOT/timeouts-comparison.json" >/dev/null || \
  fail "timeout-only cohorts should produce null paired averages"

write_run "$TEST_ROOT/disjoint-baseline" 1 1 1000 1
write_timeout "$TEST_ROOT/disjoint-current" 1 1
write_timeout "$TEST_ROOT/disjoint-baseline" 2 1
write_run "$TEST_ROOT/disjoint-current" 2 1 500 2
python3 "$COMPARATOR" \
  --catalog "$TEST_ROOT/catalog.json" \
  --baseline "$TEST_ROOT/disjoint-baseline" \
  --current "$TEST_ROOT/disjoint-current" \
  --output "$TEST_ROOT/disjoint-comparison.json"
jq -e '
  .portfolio.baseline.tokens.measured_runs == 1 and
  .portfolio.current.tokens.measured_runs == 1 and
  .portfolio.paired_measured.baseline.runs == 0 and
  .portfolio.paired_measured.current.runs == 0 and
  .portfolio.paired_measured.delta.token_efficiency_percent == null
' "$TEST_ROOT/disjoint-comparison.json" >/dev/null || \
  fail "disjoint measured cohorts should produce empty paired summaries"

echo "change path benchmark fixtures passed"
