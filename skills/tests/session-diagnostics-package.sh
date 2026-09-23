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

default_target="$TEST_ROOT/default"
"$SKILLS_DIR/install.sh" -f -d "$default_target" >/dev/null
test ! -e "$default_target/varde-diagnose" ||
  fail "default catalogue installed optional diagnostics"

pack_target="$TEST_ROOT/pack"
"$SKILLS_DIR/install.sh" -f -d "$pack_target" --pack diagnostics >/dev/null
test -f "$pack_target/varde-diagnose/SKILL.md" ||
  fail "diagnostics pack omitted SKILL.md"
test -x "$pack_target/varde-diagnose/scripts/diagnose-session.py" ||
  fail "diagnostics pack omitted executable runner"

direct_target="$TEST_ROOT/direct"
"$SKILLS_DIR/install.sh" -f -d "$direct_target" -s varde-diagnose >/dev/null
test -f "$direct_target/varde-diagnose/SKILL.md" ||
  fail "direct diagnostics selection failed"

transcript="$TEST_ROOT/session.log"
report="$TEST_ROOT/report.md"
protected="$TEST_ROOT/protected.txt"
printf '%s\n' protected > "$protected"
before="$(cksum "$protected")"
printf '%s\n' \
  'timestamp=2026-09-21T10:00:00Z skill=varde-change mode=build evidence=present outcome=complete' \
  > "$transcript"
python3 "$pack_target/varde-diagnose/scripts/diagnose-session.py" \
  --transcript "$transcript" --report "$report"
grep -F 'transcript: available' "$report" >/dev/null ||
  fail "installed diagnostics invocation failed"
after="$(cksum "$protected")"
[ "$before" = "$after" ] || fail "diagnostics changed a protected source"

echo "session diagnostics package fixtures passed"
