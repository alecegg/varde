#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for skill_name in varde-change varde-docs varde-knowledge; do
  reference="$SKILLS_DIR/$skill_name/references/varde-workflow-cli.md"
  grep -Fq '## Decision rule' "$reference" || \
    fail "$skill_name lacks a Workflow CLI decision rule"
  grep -Fq '**Known content:**' "$reference" || \
    fail "$skill_name lacks direct-read guidance"
  grep -Fq '**Discovery:**' "$reference" || \
    fail "$skill_name lacks discovery guidance"
  grep -Fq '**Mutation:**' "$reference" || \
    fail "$skill_name lacks safe-write guidance"
  grep -Fq '**Output scope:**' "$reference" || \
    fail "$skill_name lacks output guidance"
  grep -Fq '**Candidate reads:**' "$reference" || \
    fail "$skill_name lacks candidate-read guidance"
done

grep -Fq '## The workflow state machine' \
  "$SKILLS_DIR/varde-change/references/varde-workflow-cli.md" || \
  fail "change lost workflow-state guidance"

for skill_name in varde-docs varde-knowledge; do
  reference="$SKILLS_DIR/$skill_name/references/varde-workflow-cli.md"
  if grep -Fq '## The workflow state machine' "$reference"; then
    fail "$skill_name loads unrelated plan-state guidance"
  fi
done

grep -Fq 'Read one known note directly when no mutation follows.' \
  "$SKILLS_DIR/varde-knowledge/references/note.md" || \
  fail "knowledge reads known notes through the CLI"
grep -Fq 'only for' "$SKILLS_DIR/varde-docs/references/refresh.md" || \
  fail "docs loads Workflow CLI guidance eagerly"
grep -Fq 'On failure, preserve bytes and stop.' \
  "$SKILLS_DIR/varde-docs/references/varde-workflow-cli.md" || \
  fail "docs permits unsafe mutation fallback"

for skill_name in varde-docs varde-knowledge; do
  reference="$SKILLS_DIR/$skill_name/references/varde-workflow-cli.md"
  if grep 'concept search' "$reference" | grep -Fq -- '--json'; then
    fail "$skill_name requests verbose JSON search output"
  fi
done

if grep -F 'concept list' \
  "$SKILLS_DIR/varde-docs/references/varde-workflow-cli.md" | \
  grep -Fq -- '--field'; then
  fail "docs passes unsupported --field to concept list"
fi

echo "Workflow CLI routing fixtures passed."
