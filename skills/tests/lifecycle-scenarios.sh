#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATOR="$SKILLS_DIR/benchmarks/validate-lifecycle-scenarios.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

expect_invalid() {
  local fixture="$1"
  if "$VALIDATOR" "$fixture" >/dev/null 2>&1; then
    fail "expected invalid catalog: $(basename "$fixture")"
  fi
}

valid="$TEST_ROOT/valid.json"
cat > "$valid" <<'JSON'
{
  "schema_version": 1,
  "scenarios": [
    {
      "id": "plan-build-verify",
      "name": "Plan, build, and verify a bounded change",
      "setup": ["Prepare a disposable repository with one ready plan."],
      "workflow_actions": ["Plan the change.", "Build every task.", "Verify acceptance criteria."],
      "observable_assertions": ["The plan finishes with every task done."],
      "evidence_paths": ["memory-bank/working/plans/example/plan.md"],
      "token_capture": {
        "method": "Record harness usage after each workflow action.",
        "evidence_path": "benchmark-runs/plan-build-verify/tokens.json",
        "fields": ["input_tokens", "output_tokens"]
      }
    }
  ]
}
JSON

"$VALIDATOR" "$valid" >/dev/null || fail "valid fixture was rejected"

invalid_json="$TEST_ROOT/invalid-json.json"
printf '%s\n' '{"schema_version":' > "$invalid_json"
expect_invalid "$invalid_json"

unsupported_version="$TEST_ROOT/unsupported-version.json"
jq '.schema_version = 2' "$valid" > "$unsupported_version"
expect_invalid "$unsupported_version"

empty_scenarios="$TEST_ROOT/empty-scenarios.json"
jq '.scenarios = []' "$valid" > "$empty_scenarios"
expect_invalid "$empty_scenarios"

missing_field="$TEST_ROOT/missing-field.json"
jq 'del(.scenarios[0].evidence_paths)' "$valid" > "$missing_field"
expect_invalid "$missing_field"

empty_collection="$TEST_ROOT/empty-collection.json"
jq '.scenarios[0].observable_assertions = []' "$valid" > "$empty_collection"
expect_invalid "$empty_collection"

blank_collection_item="$TEST_ROOT/blank-collection-item.json"
jq '.scenarios[0].setup = [" "]' "$valid" > "$blank_collection_item"
expect_invalid "$blank_collection_item"

invalid_token_capture="$TEST_ROOT/invalid-token-capture.json"
jq '.scenarios[0].token_capture.fields = []' "$valid" > "$invalid_token_capture"
expect_invalid "$invalid_token_capture"

duplicate_id="$TEST_ROOT/duplicate-id.json"
jq '.scenarios += [.scenarios[0]]' "$valid" > "$duplicate_id"
expect_invalid "$duplicate_id"

echo "lifecycle scenario fixtures passed"
