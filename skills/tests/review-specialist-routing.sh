#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SELECTOR="$SKILLS_DIR/varde-review/scripts/select-review-specialists.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_text() {
  local file="$1"
  local text="$2"
  grep -F "$text" "$file" >/dev/null || fail "$file lacks: $text"
}

test -x "$SELECTOR" || fail "specialist selector is missing or not executable"

low_risk="$($SELECTOR correctness,code,architecture)"
[ -z "$low_risk" ] || fail "low-risk review selected specialists: $low_risk"

high_risk="$($SELECTOR security,data-integrity,performance)"
expected=$'security\ndata-integrity'
[ "$high_risk" = "$expected" ] ||
  fail "high-risk review selected $high_risk, expected $expected"

single_risk="$($SELECTOR performance)"
[ "$single_risk" = "performance" ] ||
  fail "single risk selected $single_risk, expected performance"

require_text "$SKILLS_DIR/varde-review/references/report-routing.md" \
  "unified coordinator"
require_text "$SKILLS_DIR/varde-review/references/report-routing.md" \
  "at most two"
require_text "$SKILLS_DIR/varde-review/references/report.md" \
  "report-routing.md"

echo "Review specialist routing fixtures passed."
