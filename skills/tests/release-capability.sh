#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

installed="$TEST_ROOT/installed"
"$SKILLS_DIR/install.sh" -f -d "$installed" --pack shipping >/dev/null

test -f "$installed/varde-release/SKILL.md" ||
  fail "release skill was not installed"
test -x "$installed/varde-release/scripts/detect-release-tools.sh" ||
  fail "release capability probe is not executable"

empty_path="$TEST_ROOT/empty-path"
mkdir -p "$empty_path"
degraded_output="$({ PATH="$empty_path" /bin/bash \
  "$installed/varde-release/scripts/detect-release-tools.sh"; })"
printf '%s\n' "$degraded_output" | grep -Fx 'capability=degraded' >/dev/null ||
  fail "missing release tooling did not report degraded capability"
printf '%s\n' "$degraded_output" | grep -F 'guidance=' >/dev/null ||
  fail "degraded output omitted bounded guidance"
[ "$(printf '%s\n' "$degraded_output" | wc -l | tr -d ' ')" -le 3 ] ||
  fail "degraded guidance exceeded the bounded output"

guard="$installed/varde-release/scripts/authorize-release-action.sh"
for action in publish deploy rollback; do
  unauthorized_output="$TEST_ROOT/$action-unauthorized"
  if "$guard" "$action" >"$unauthorized_output" 2>&1; then
    fail "$action was accepted without authorization"
  fi
  grep -Fx 'authorization=absent' "$unauthorized_output" >/dev/null ||
    fail "$action omitted absent authorization evidence"

  authorized_output="$(VARDE_RELEASE_AUTHORIZED=1 "$guard" "$action")"
  printf '%s\n' "$authorized_output" |
    grep -Fx "authorization=granted action=$action" >/dev/null ||
    fail "$action did not require explicit authorization"
done
