#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS_DIR="$(cd "$SKILLS_DIR/../agents" && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for profile in plan executor review explore; do
  prompt="$AGENTS_DIR/$profile/claude.md"
  grep -Fq 'degraded capability' "$prompt" || \
    fail "$profile prompt does not report degraded capability"
  grep -Fq 'manual evidence' "$prompt" || \
    fail "$profile prompt does not name manual evidence"
done

for reference in \
  "$SKILLS_DIR"/varde-change/references/varde-code.md \
  "$SKILLS_DIR"/varde-explore/references/varde-code.md \
  "$SKILLS_DIR"/varde-review/references/varde-code.md \
  "$SKILLS_DIR"/varde-docs/references/varde-code.md; do
  grep -Fq 'use Read/Grep' "$reference" || \
    fail "$reference lacks a manual Varde Code fallback"
  grep -Fq 'name the degraded capability' "$reference" || \
    fail "$reference lacks fallback evidence reporting"
done

for reference in \
  "$SKILLS_DIR"/varde-change/references/varde-workflow-cli.md \
  "$SKILLS_DIR"/varde-docs/references/varde-workflow-cli.md \
  "$SKILLS_DIR"/varde-knowledge/references/varde-workflow-cli.md; do
  grep -Eq 'plain (Read and Grep|reads and searches)|Continue read-only operations with Read or Grep' "$reference" || \
    fail "$reference lacks a manual Workflow CLI fallback"
  grep -Fq 'stop every mutation' "$reference" || \
    fail "$reference lacks mutation fallback evidence"
done

echo "CLI fallback evidence contracts passed."
