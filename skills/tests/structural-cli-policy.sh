#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for skill_name in varde-change varde-explore varde-review varde-docs; do
  reference="$SKILLS_DIR/$skill_name/references/varde-code.md"
  [ -f "$reference" ] || fail "missing Varde Code policy: $skill_name"
  grep -Fq '## Decision rule' "$reference" || \
    fail "$skill_name lacks a Varde Code decision rule"
  grep -Fq '**Discovery and relationships:**' "$reference" || \
    fail "$skill_name lacks unknown-scope discovery guidance"
  grep -Fq '**Known content:**' "$reference" || \
    fail "$skill_name lacks direct-read guidance"
  grep -Fq '**New or trivial targets:** Skip indexing.' "$reference" || \
    fail "$skill_name indexes known trivial targets"
  grep -Fq 'Confirm important' "$reference" || \
    fail "$skill_name lacks source confirmation guidance"
done

echo "Structural CLI policy contracts passed."
