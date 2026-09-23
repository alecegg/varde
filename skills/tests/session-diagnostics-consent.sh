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

transcript="$TEST_ROOT/historical-session.log"
cat > "$transcript" <<'TRANSCRIPT'
timestamp=2026-09-21T10:00:00Z skill=varde-change mode=build route=debug evidence=present token=TOKEN-123 outcome=complete
TRANSCRIPT

unauthorized_report="$TEST_ROOT/unauthorized.md"
if python3 "$RUNNER" --source historical --session-id old-session \
  --transcript "$transcript" --report "$unauthorized_report"; then
  fail "historical access succeeded without consent"
fi
grep -F 'explicit historical consent is required' "$unauthorized_report" >/dev/null ||
  fail "historical refusal omitted authorization request"
grep -F 'TOKEN-123' "$unauthorized_report" >/dev/null &&
  fail "historical refusal read transcript content"

fallback_report="$TEST_ROOT/fallback.md"
if VARDE_CURRENT_SESSION_TRANSCRIPT="$transcript" python3 "$RUNNER" \
  --source historical --session-id old-session --historical-consent \
  --report "$fallback_report"; then
  fail "historical mode used current-session fallback"
fi
grep -F 'historical transcript path is required' "$fallback_report" >/dev/null ||
  fail "historical fallback refusal omitted explicit path requirement"

authorized_report="$TEST_ROOT/authorized.md"
python3 "$RUNNER" --source historical --session-id old-session \
  --historical-consent --transcript "$transcript" --report "$authorized_report"
grep -F 'transcript: available' "$authorized_report" >/dev/null ||
  fail "authorized historical access did not run"

expired_report="$TEST_ROOT/expired.md"
if python3 "$RUNNER" --source historical --session-id old-session \
  --transcript "$transcript" --report "$expired_report"; then
  fail "prior-run historical consent was reused"
fi
grep -F 'consent expired' "$expired_report" >/dev/null ||
  fail "expired consent was not reported"

current_report="$TEST_ROOT/current.md"
no_export="$TEST_ROOT/no-export"
python3 "$RUNNER" --transcript "$transcript" --report "$current_report" \
  --export-dir "$no_export"
test ! -e "$no_export" || fail "export was created without separate consent"

export_dir="$TEST_ROOT/export"
export_report="$TEST_ROOT/export-report.md"
python3 "$RUNNER" --transcript "$transcript" --report "$export_report" \
  --export-dir "$export_dir" --export-consent --redact-pattern 'TOKEN-123'
test -f "$export_dir/report.md" || fail "authorized export omitted report"
test -f "$export_dir/transcript.log" || fail "authorized export omitted transcript"
if grep -R -F 'TOKEN-123' "$export_dir" >/dev/null; then
  fail "configured sensitive pattern survived export"
fi
grep -R -F 'Residual risk' "$export_dir" >/dev/null ||
  fail "export omitted residual-risk disclosure"

echo "session diagnostics consent fixtures passed"
