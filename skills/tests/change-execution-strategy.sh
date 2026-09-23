#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SELECTOR="$SKILLS_DIR/varde-change/scripts/select-execution-strategy.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_text() {
  local file="$1"
  local text="$2"
  grep -F "$text" "$file" >/dev/null || fail "$file lacks: $text"
}

run_case() {
  local requested="$1"
  local task_count="$2"
  local expected="$3"
  local actual
  actual="$($SELECTOR "$requested" "$task_count")"
  [ "$actual" = "$expected" ] ||
    fail "$requested with $task_count tasks resolved to $actual, expected $expected"
}

test -x "$SELECTOR" || fail "strategy selector is missing or not executable"
run_case inline 1 inline
run_case inline 4 inline
run_case fresh 1 fresh
run_case fresh 4 fresh
run_case auto 1 inline
run_case auto 4 fresh

cat > "$TEST_ROOT/independent.json" <<'JSON'
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/alpha"],"creates":[],"renames":[],"verification_resources":["impact:src/alpha-consumer"]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/beta"],"creates":[],"renames":[],"verification_resources":["impact:src/beta-consumer"]}
  ]
}
JSON
cat > "$TEST_ROOT/conflict.json" <<'JSON'
{
  "harness_capacity": 2,
  "max_parallel_workers": 2,
  "tasks": [
    {"id":"alpha","status":"todo","depends_on":[],"modifies":["src/shared"],"creates":[],"renames":[],"verification_resources":["impact:src/shared-consumer"]},
    {"id":"beta","status":"todo","depends_on":[],"modifies":["src/shared/file"],"creates":[],"renames":[],"verification_resources":["impact:src/shared-consumer"]}
  ]
}
JSON
[ "$($SELECTOR auto "$TEST_ROOT/independent.json")" = parallel ] ||
  fail "auto did not select parallel for an independent manifest"
[ "$($SELECTOR auto "$TEST_ROOT/conflict.json")" = fresh ] ||
  fail "auto did not preserve sequential execution for conflicts"
[ "$($SELECTOR parallel "$TEST_ROOT/independent.json")" = parallel ] ||
  fail "explicit parallel strategy was rejected"

if "$SELECTOR" unsupported 1 >/dev/null 2>&1; then
  fail "unsupported execution strategy was accepted"
fi
if "$SELECTOR" auto 0 >/dev/null 2>&1; then
  fail "zero task count was accepted"
fi

require_text "$SKILLS_DIR/varde-change/references/build.md" \
  "execution=<auto|inline|fresh|parallel>"
require_text "$SKILLS_DIR/varde-change/references/build.md" \
  "task manifest"
require_text "$SKILLS_DIR/varde-change/references/build-dispatch.md" \
  "one task at a time"
require_text "$SKILLS_DIR/varde-change/references/build-dispatch.md" \
  "uses fresh"
require_text "$SKILLS_DIR/varde-change/references/build-dispatch.md" \
  "verification resources prove independence"
require_text "$SKILLS_DIR/varde-change/references/build-dispatch.md" \
  "recovery refs"

echo "Execution strategy fixtures passed."
