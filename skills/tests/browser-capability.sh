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
"$SKILLS_DIR/install.sh" -f -d "$installed" --pack browser >/dev/null

test -f "$installed/varde-browser/SKILL.md" ||
  fail "browser skill was not installed"
test -x "$installed/varde-browser/scripts/detect-browser.sh" ||
  fail "browser capability probe is not executable"

empty_path="$TEST_ROOT/empty-path"
mkdir -p "$empty_path"
degraded_output="$(PATH="$empty_path" /bin/bash \
  "$installed/varde-browser/scripts/detect-browser.sh")"
printf '%s\n' "$degraded_output" | grep -Fx 'capability=degraded' >/dev/null ||
  fail "missing browser tooling did not report degraded capability"
printf '%s\n' "$degraded_output" | grep -F 'guidance=' >/dev/null ||
  fail "degraded output omitted bounded guidance"
[ "$(printf '%s\n' "$degraded_output" | wc -l | tr -d ' ')" -le 3 ] ||
  fail "degraded guidance exceeded the bounded output"
