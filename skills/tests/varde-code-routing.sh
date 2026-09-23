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
  grep -Fq '## Decision rule' "$reference" || \
    fail "$skill_name lacks a Varde Code decision rule"
  grep -Fq '**Discovery and relationships:**' "$reference" || \
    fail "$skill_name lacks discovery guidance"
  grep -Fq '**Known content:**' "$reference" || \
    fail "$skill_name lacks direct-read guidance"
  grep -Fq '**Large known files:**' "$reference" || \
    fail "$skill_name lacks the get_symbol exception"
  grep -Fq '**Batch related lookups:**' "$reference" || \
    fail "$skill_name lacks batching guidance"
  grep -Fq '**New or trivial targets:**' "$reference" || \
    fail "$skill_name lacks skip-indexing guidance"
done

grep -Fq 'Read the specified file or directory directly.' \
  "$SKILLS_DIR/varde-explore/references/explain-section.md" || \
  fail "explore path targets do not prefer direct reads"
grep -Fq 'Read one short, known source file directly.' \
  "$SKILLS_DIR/varde-docs/references/varde-code.md" || \
  fail "docs does not prefer direct reads for known content"
grep -Fq 'Read known changed lines directly.' \
  "$SKILLS_DIR/varde-review/references/simplify.md" || \
  fail "simplify does not prefer direct reads"
grep -Fq 'discovery or relationship questions' \
  "$SKILLS_DIR/varde-change/references/build-plan.md" || \
  fail "general build guidance loads Varde Code eagerly"

echo "Varde Code routing fixtures passed."
