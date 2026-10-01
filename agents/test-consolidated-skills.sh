#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_role_text() {
  local role="$1"
  shift
  local file text

  for file in "$AGENTS_DIR/$role"/*; do
    for text in "$@"; do
      grep -Fi "$text" "$file" >/dev/null ||
        fail "$(basename "$file") lacks role text: $text"
    done
  done
}

require_role_text varde-planner "varde-change plan" "Do not implement"
require_role_text varde-executor "varde-change build" "loaded \`varde-review\` skill" "not a shell executable"
require_role_text varde-reviewer "loaded \`varde-review\` skill" "is a skill workflow, not a shell command" "not a shell executable" "never edit production source"
require_role_text varde-explorer "varde-explore" "Do not implement"

grep -F "skills: varde-change" "$AGENTS_DIR/varde-planner/claude.md" >/dev/null
grep -F "skills: varde-change, varde-review" "$AGENTS_DIR/varde-executor/claude.md" >/dev/null
grep -F "skills: varde-review" "$AGENTS_DIR/varde-reviewer/claude.md" >/dev/null
grep -F "skills: varde-explore" "$AGENTS_DIR/varde-explorer/claude.md" >/dev/null

if rg -nP 'varde-(dashboard|explain|plan\b|build|orchestrate|review-fix|simplify|spec|reflect|friction|handoff|worktree|code-(?!cli\.md))' \
  "$AGENTS_DIR"/{varde-planner,varde-executor,varde-reviewer,varde-explorer}; then
  fail "agent definitions reference retired skills"
fi

"$AGENTS_DIR/tests/generated-adapters.sh"
python3 "$AGENTS_DIR/tests/opencode-v2-permissions.py"
bash "$AGENTS_DIR/tests/opencode-install-migration.sh"
"$AGENTS_DIR/tests/review-fix-routing.sh"
