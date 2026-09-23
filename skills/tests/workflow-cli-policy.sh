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
  [ -f "$reference" ] || fail "missing Workflow CLI policy: $skill_name"
  grep -Fq 'optional' "$reference" || \
    fail "$skill_name makes Workflow CLI mandatory"
  grep -Fq '## Decision rule' "$reference" || \
    fail "$skill_name lacks a Workflow CLI decision rule"
  grep -Fq '**Known content:**' "$reference" || \
    fail "$skill_name lacks direct-read guidance"
  grep -Fq '**Mutation:** Use state commands' "$reference" || \
    fail "$skill_name lacks state-safe mutation guidance"
  grep -Fq 'Stop before CLI-owned mutations.' "$reference" || \
    fail "$skill_name lacks mutation fallback boundary"
done

grep -Fq '## The workflow state machine' \
  "$SKILLS_DIR/varde-change/references/varde-workflow-cli.md" || \
  fail "change lacks task and plan state ownership"

echo "Workflow CLI policy contracts passed."
