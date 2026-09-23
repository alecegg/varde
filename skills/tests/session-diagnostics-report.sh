#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SKILLS_DIR/varde-diagnose/scripts/diagnose-session.py"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

transcript="$TEST_ROOT/current-session.log"
report="$TEST_ROOT/report.md"
cat > "$transcript" <<'TRANSCRIPT'
timestamp=2026-09-21T10:00:00Z skill=varde-change mode=build request=bug route=generic decision=continue evidence=missing outcome=started
timestamp=2026-09-21T10:01:00Z skill=varde-change mode=build plan=deviation decision=continue evidence=present outcome=started
timestamp=2026-09-21T10:02:00Z skill=varde-change mode=build request=bug route=generic decision=continue evidence=missing outcome=started
timestamp=2026-09-21T10:03:00Z skill=varde-change mode=build request=bug route=generic decision=continue evidence=missing outcome=started
TRANSCRIPT

python3 "$RUNNER" --transcript "$transcript" --report "$report"

grep -F 'transcript: available' "$report" >/dev/null ||
  fail "available transcript was not reported"
grep -F 'routing' "$report" >/dev/null ||
  fail "routing finding was omitted"
grep -F 'plan' "$report" >/dev/null ||
  fail "plan finding was omitted"
grep -F 'repeated' "$report" >/dev/null ||
  fail "repeated-work finding was omitted"
grep -F 'evidence' "$report" >/dev/null ||
  fail "evidence finding was omitted"

finding_lines="$(grep -E '^### ' "$report" | wc -l | tr -d ' ')"
[ "$finding_lines" -eq 4 ] ||
  fail "expected four findings, got $finding_lines"

while IFS= read -r evidence_line; do
  line_number="$(printf '%s\n' "$evidence_line" | sed -n 's/.*transcript line \([0-9][0-9]*\).*/\1/p')"
  [ -n "$line_number" ] || fail "finding omitted a transcript line citation"
  [ "$line_number" -ge 1 ] && [ "$line_number" -le 4 ] ||
    fail "finding cited a line outside the transcript"
done < <(grep -F 'transcript line ' "$report")

unavailable_report="$TEST_ROOT/unavailable.md"
python3 "$RUNNER" --transcript "$TEST_ROOT/missing.log" \
  --report "$unavailable_report"
grep -F 'transcript: unavailable' "$unavailable_report" >/dev/null ||
  fail "unavailable transcript was not reported"
grep -F 'missing.log' "$unavailable_report" >/dev/null ||
  fail "unavailable source was not named"
grep -F 'No findings.' "$unavailable_report" >/dev/null ||
  fail "unavailable transcript fabricated findings"
if grep -q '^### ' "$unavailable_report"; then
  fail "unavailable transcript contained finding headings"
fi

echo "session diagnostics report fixtures passed"
