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

require_role_text plan "varde-change plan" "Do not implement"
require_role_text executor "varde-change build" "loaded \`varde-review\` skill" "not a shell executable"
require_role_text review "loaded \`varde-review\` skill" "is a skill workflow, not a shell command" "not a shell executable" "never edit production source"
require_role_text explore "varde-explore" "Do not implement"

grep -F "skills: varde-change" "$AGENTS_DIR/plan/claude.md" >/dev/null
grep -F "skills: varde-change, varde-review" "$AGENTS_DIR/executor/claude.md" >/dev/null
grep -F "skills: varde-review" "$AGENTS_DIR/review/claude.md" >/dev/null
grep -F "skills: varde-explore" "$AGENTS_DIR/explore/claude.md" >/dev/null

if rg -n 'varde-(dashboard|explain|plan|build|orchestrate|review-fix|simplify|spec|reflect|friction|handoff|worktree|code-)' \
  "$AGENTS_DIR"/{plan,executor,review,explore}; then
  fail "agent definitions reference retired skills"
fi

"$AGENTS_DIR/tests/generated-adapters.sh"
python3 "$AGENTS_DIR/tests/opencode-v2-permissions.py"
bash "$AGENTS_DIR/tests/opencode-install-migration.sh"
"$AGENTS_DIR/tests/review-fix-routing.sh"
