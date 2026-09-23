#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NORMALIZER="$SKILLS_DIR/varde-review/scripts/normalize-review-candidates.sh"
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

test -x "$NORMALIZER" || fail "candidate normalizer is missing or not executable"

valid='src/auth.ts:42	security	high	Token path reaches shell input	Command injection risk	Existing sanitizer was checked	triage'
unsupported='src/auth.ts:42	mystery	high	Unsupported category	No supported review owner	No refutation available	triage'
candidate_file="$TEST_ROOT/candidates.tsv"
error_file="$TEST_ROOT/rejections.log"
printf '%b\n%b\n%b\n' "$valid" "$valid" "$unsupported" > "$candidate_file"

normalized="$($NORMALIZER "$candidate_file" 2>"$error_file")"
[ "$normalized" = "$(printf '%b' "$valid")" ] ||
  fail "normalizer output was not one verified unique candidate: $normalized"
grep -F "duplicate candidate rejected" "$error_file" >/dev/null ||
  fail "duplicate candidate rejection was not reported"
grep -F "unsupported category rejected" "$error_file" >/dev/null ||
  fail "unsupported category rejection was not reported"

require_text "$SKILLS_DIR/varde-review/references/report-candidates.md" \
  "coordinator"
require_text "$SKILLS_DIR/varde-review/references/report-candidates.md" \
  "Refutation"
require_text "$SKILLS_DIR/varde-review/references/report.md" \
  "report-candidates.md"

echo "Review candidate coordination fixtures passed."
