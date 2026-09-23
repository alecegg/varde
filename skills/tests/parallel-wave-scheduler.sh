#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SELECTOR="$SKILLS_DIR/varde-change/scripts/select-execution-strategy.sh"
RESOLVER="$SKILLS_DIR/varde-change/scripts/resolve-execution-wave.py"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cat > "$TEST_ROOT/independent.json" <<'JSON'
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/alpha"],"creates":[],"renames":[],"verification_resources":["impact:src/alpha-consumer"]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/beta"],"creates":[],"renames":[],"verification_resources":["impact:src/beta-consumer"]},
    {"id":"follow-up","status":"todo","depends_on":["alpha","beta"],"modifies":["src/follow-up"],"creates":[],"renames":[],"verification_resources":["impact:src/follow-up-consumer"]}
  ]
}
JSON

cat > "$TEST_ROOT/conflict.json" <<'JSON'
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"left","status":"todo","depends_on":[],"modifies":["src/left"],"creates":[],"renames":[],"verification_resources":["impact:src/shared-consumer"]},
    {"id":"right","status":"todo","depends_on":[],"modifies":["src/right"],"creates":[],"renames":[],"verification_resources":["impact:src/shared-consumer"]}
  ]
}
JSON

cat > "$TEST_ROOT/unknown.json" <<'JSON'
{
  "harness_capacity": 2,
  "tasks": [
    {"id":"known","status":"todo","depends_on":[],"modifies":["src/known"],"creates":[],"renames":[],"verification_resources":["impact:src/known-consumer"]},
    {"id":"unknown","status":"todo","depends_on":[],"modifies":["src/unknown"]}
  ]
}
JSON

cat > "$TEST_ROOT/no-impact.json" <<'JSON'
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/alpha"],"creates":[],"renames":[],"verification_resources":[]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/beta"],"creates":[],"renames":[],"verification_resources":[]}
  ]
}
JSON

cat > "$TEST_ROOT/over-capacity.json" <<'JSON'
{
  "harness_capacity": 1,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/alpha"],"creates":[],"renames":[],"verification_resources":[]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/beta"],"creates":[],"renames":[],"verification_resources":[]}
  ]
}
JSON

cat > "$TEST_ROOT/single-worker.json" <<'JSON'
{
  "harness_capacity": 1,
  "max_parallel_workers": 1,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/alpha"],"creates":[],"renames":[],"verification_resources":["impact:src/alpha-consumer"]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/beta"],"creates":[],"renames":[],"verification_resources":["impact:src/beta-consumer"]}
  ]
}
JSON

cat > "$TEST_ROOT/incomplete-rename.json" <<'JSON'
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/alpha"],"creates":[],"renames":[{"from":"src/old"}],"verification_resources":[]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/beta"],"creates":[],"renames":[],"verification_resources":[]}
  ]
}
JSON

test -x "$SELECTOR" || fail "strategy selector is missing or not executable"
test -x "$RESOLVER" || fail "execution-wave resolver is missing or not executable"
[ "$($SELECTOR auto "$TEST_ROOT/independent.json")" = parallel ] ||
  fail "independent manifest did not select parallel"
[ "$($SELECTOR auto "$TEST_ROOT/conflict.json")" = fresh ] ||
  fail "conflicting manifest did not fall back to fresh"
[ "$($SELECTOR auto "$TEST_ROOT/unknown.json")" = fresh ] ||
  fail "unknown ownership did not fall back to fresh"
[ "$($SELECTOR auto "$TEST_ROOT/incomplete-rename.json")" = fresh ] ||
  fail "incomplete rename ownership did not fall back to fresh"
[ "$($SELECTOR auto "$TEST_ROOT/single-worker.json")" = fresh ] ||
  fail "single-worker limit did not fall back to fresh"

if "$SELECTOR" parallel "$TEST_ROOT/single-worker.json" >/dev/null 2>&1; then
  fail "single-worker limit accepted explicit parallel execution"
fi

if "$SELECTOR" parallel "$TEST_ROOT/over-capacity.json" >/dev/null 2>&1; then
  fail "capacity overflow was accepted"
fi

jq -e '
  .schema_version == 1 and
  .ready_tasks == ["alpha", "beta"] and
  .waves == [["alpha", "beta"], ["follow-up"]] and
  .parallel_safe == true and
  .capacity == 2
' < <("$RESOLVER" "$TEST_ROOT/independent.json") >/dev/null ||
  fail "independent wave output was unexpected"

jq -e '
  (.waves | length) == 2 and
  .waves[0] == ["left"] and
  .waves[1] == ["right"] and
  .parallel_safe == false and
  (.conflicts | length) == 1 and
  .conflicts[0].reason == "impact-resource"
' < <("$RESOLVER" "$TEST_ROOT/conflict.json") >/dev/null ||
  fail "conflict matrix was not serialized"

jq -e '
  .parallel_safe == false and
  .unknown_ownership == ["unknown"] and
  .unknown_impact == ["unknown"] and
  .waves == [["known"], ["unknown"]]
' < <("$RESOLVER" "$TEST_ROOT/unknown.json") >/dev/null ||
  fail "unknown ownership was not isolated"

[ "$($SELECTOR auto "$TEST_ROOT/no-impact.json")" = fresh ] ||
  fail "missing impact evidence did not fall back to fresh"
jq -e '
  .parallel_safe == false and
  .unknown_impact == ["alpha", "beta"] and
  .waves == [["alpha"], ["beta"]]
' < <("$RESOLVER" "$TEST_ROOT/no-impact.json") >/dev/null ||
  fail "missing impact evidence was not isolated"

if "$RESOLVER" "$TEST_ROOT/over-capacity.json" >/dev/null 2>&1; then
  fail "resolver accepted a worker limit above capacity"
fi

jq -e '
  .parallel_safe == true and
  .ready_tasks == ["alpha", "beta"] and
  .waves == [["alpha"], ["beta"]]
' < <("$RESOLVER" "$TEST_ROOT/single-worker.json") >/dev/null ||
  fail "single-worker waves were not serialized"

echo "Parallel wave scheduler fixtures passed."
