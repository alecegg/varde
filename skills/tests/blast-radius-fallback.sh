#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

template="$REPO_ROOT/skills/varde-change/assets/TASK-TEMPLATE.md"
fundamentals="$REPO_ROOT/skills/varde-change/references/plan-fundamentals.md"
code_reference="$REPO_ROOT/skills/varde-change/references/varde-code.md"

grep -Fq 'If `varde-code` is unavailable' "$template" ||
  fail "task template omits manual fallback"
grep -Fq 'name the manually inspected' "$template" ||
  fail "task template omits manual evidence names"
grep -Fq 'If `varde-code` is unavailable' "$fundamentals" ||
  fail "planning guidance omits manual fallback"
grep -Fq 'evidence remains valid' "$fundamentals" ||
  fail "planning guidance rejects valid manual evidence"
grep -Fq 'unavailable, record the manual' "$code_reference" ||
  fail "varde-code reference omits manual fallback"
grep -Fq 'relevant tests' "$code_reference" ||
  fail "varde-code reference omits relevant test evidence"

echo "Blast-radius fallback fixtures passed."
