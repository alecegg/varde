#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$SCRIPT_DIR/../varde-agent-doc-authoring"
EVALS="$SKILL_DIR/evals/evals.json"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agent-doc-authoring-evals.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

jq -e '.skill_name == "varde-agent-doc-authoring" and (.evals | type == "array")' \
  "$EVALS" >/dev/null || fail "evals.json is invalid"

while IFS= read -r fixture; do
  [ -f "$SKILL_DIR/$fixture" ] || fail "declared fixture is missing: $fixture"
done < <(jq -r '.evals[].files[]?' "$EVALS")

check_declared_assertion() {
  local eval_id="$1" result_file="$2" declared
  declared="$(jq -c --arg id "$eval_id" '.evals[] | select((.id | tostring) == $id) | .assertions' "$EVALS")"
  jq -e --argjson declared "$declared" \
    '.results | all(.[]; .assertion as $a | ($declared | index($a)) != null)' \
    "$result_file" >/dev/null || fail "verifier result contains an undeclared assertion for eval $eval_id"
}

# Smoke-test each verifier's declared-assertion contract on a valid artifact.
# Edge cases (missing artifact, ranking gap, symlinked output) are dropped
# here; the jq fixture-exists and declaration checks above are the guard.
sandbox="$TEST_ROOT/sandbox"
mkdir -p "$sandbox"
report_verifier="$SKILL_DIR/evals/verify-self-audit.sh"
cat > "$sandbox/stale-notes.md" <<'REPORT'
# Stale notes

1. Pre-existing file that predates the run; must not count as the report.
2. Second entry.
REPORT
touch -t 202001010000 "$sandbox/stale-notes.md"
run_start="$(date +%s)"
cat > "$sandbox/audit-report.md" <<'REPORT'
# Audit report

1. Remove an instruction that adds no useful behavior.
2. Keep the load-bearing workflow guidance.
REPORT
EVAL_SANDBOX_DIR="$sandbox" EVAL_RUN_START="$run_start" bash "$report_verifier" > "$TEST_ROOT/report-valid.json"
jq -e '.results[0].verdict == "PASS"' "$TEST_ROOT/report-valid.json" >/dev/null \
  || fail "report verifier rejects a sequential ranked inventory"
check_declared_assertion 1 "$TEST_ROOT/report-valid.json"

rm -f "$sandbox/audit-report.md"
EVAL_SANDBOX_DIR="$sandbox" EVAL_RUN_START="$run_start" bash "$report_verifier" > "$TEST_ROOT/report-stale.json"
jq -e '.results[0].verdict == "FAIL"' "$TEST_ROOT/report-stale.json" >/dev/null \
  || fail "report verifier accepts a pre-existing markdown file that predates the run"
rm -f "$sandbox/stale-notes.md"

skill_verifier="$SKILL_DIR/evals/verify-release-skill.sh"
mkdir -p "$sandbox/deploy-release"
printf '%s\n' '---' 'name: deploy-release' 'description: "Cut a release. Not for anything else."' '---' > "$sandbox/deploy-release/SKILL.md"
EVAL_SANDBOX_DIR="$sandbox" bash "$skill_verifier" > "$TEST_ROOT/skill-valid.json"
jq -e '.results[0].verdict == "PASS"' "$TEST_ROOT/skill-valid.json" >/dev/null \
  || fail "release verifier rejects an artifact at the sandbox-relative path"
check_declared_assertion 3 "$TEST_ROOT/skill-valid.json"

echo "PASS: agent doc authoring eval fixtures and artifact verifiers"
