#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATOR="$SKILLS_DIR/varde-change/scripts/validate-task-evidence.sh"
FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_DIR"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_text() {
  local file="$1"
  local text="$2"
  grep -F "$text" "$file" >/dev/null || fail "$file lacks: $text"
}

write_fixture() {
  local fixture="$1"
  local profile="$2"
  local checks="$3"
  local rationale="${4:-Exercise the selected evidence profile.}"
  cat > "$fixture" <<EOF
---
type: task
status: done
---

Example task

#### Test approach

profile: $profile
rationale: $rationale

#### Progress

- evidence: profile=$profile; checks=$checks; result=pass; note=fixture passed
EOF
}

assert_valid() {
  local profile="$1"
  local checks="$2"
  local fixture="$FIXTURE_DIR/$profile.md"
  write_fixture "$fixture" "$profile" "$checks"
  "$VALIDATOR" "$fixture" >/dev/null || fail "$profile fixture was rejected"
}

assert_invalid() {
  local name="$1"
  local fixture="$FIXTURE_DIR/$name.md"
  shift
  write_fixture "$fixture" "$@"
  if "$VALIDATOR" "$fixture" >/dev/null 2>&1; then
    fail "$name fixture was accepted"
  fi
}

test -x "$VALIDATOR" || fail "task evidence validator is missing or not executable"
assert_valid tdd red,green,verify
assert_valid regression reproduce,fix,verify
assert_valid characterization characterize,verify
assert_valid smoke smoke,verify
assert_valid not-applicable not-applicable,structural

assert_invalid unknown-profile unknown checks
assert_invalid wrong-checks tdd reproduce,fix,verify

missing_rationale="$FIXTURE_DIR/missing-rationale.md"
write_fixture "$missing_rationale" tdd red,green,verify ""
sed '/^rationale:/d' "$missing_rationale" > "$missing_rationale.tmp"
mv "$missing_rationale.tmp" "$missing_rationale"
if "$VALIDATOR" "$missing_rationale" >/dev/null 2>&1; then
  fail "missing rationale fixture was accepted"
fi

missing_evidence="$FIXTURE_DIR/missing-evidence.md"
write_fixture "$missing_evidence" smoke smoke,verify
sed '/^- evidence:/d' "$missing_evidence" > "$missing_evidence.tmp"
mv "$missing_evidence.tmp" "$missing_evidence"
if "$VALIDATOR" "$missing_evidence" >/dev/null 2>&1; then
  fail "missing evidence fixture was accepted"
fi

require_text "$SKILLS_DIR/varde-change/assets/TASK-TEMPLATE.md" \
  "profile: <tdd|regression|characterization|smoke|not-applicable>"
require_text "$SKILLS_DIR/varde-change/references/build-execution.md" \
  "profile-specific testing"
require_text "$SKILLS_DIR/varde-change/references/build-execution.md" \
  "evidence: profile=<profile>"

echo "Testing profile fixtures passed."
