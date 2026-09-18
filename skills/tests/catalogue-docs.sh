#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$SKILLS_DIR/.." && pwd)"

EXPECTED=(
  varde-agent-doc-authoring
  varde-change
  varde-docs
  varde-explore
  varde-knowledge
  varde-prototype
  varde-review
)

DOCS=(
  "$ROOT_DIR/README.md"
  "$SKILLS_DIR/README.md"
  "$ROOT_DIR/agents/README.md"
)

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for doc in "${DOCS[@]}"; do
  for skill in "${EXPECTED[@]}"; do
    grep -F "$skill" "$doc" >/dev/null || fail "$(basename "$doc") omits $skill"
  done
done

catalogue="$(sed -n '/^## Skills$/,/^## /p' "$SKILLS_DIR/README.md" | grep -o '`varde-[^`]*`' | tr -d '`' | sort -u)"
expected="$(printf '%s\n' "${EXPECTED[@]}" | sort)"
[ "$catalogue" = "$expected" ] || fail "skills catalogue differs from seven-skill manifest"

if rg -n 'varde-(dashboard|explain|plan|build|orchestrate|review-fix|simplify|spec|reflect|friction|handoff|worktree|code-)' \
  "$ROOT_DIR/README.md" "$SKILLS_DIR/README.md" "$ROOT_DIR/agents/README.md" \
  "$ROOT_DIR/AGENTS.md" "$ROOT_DIR/code-cli/README.md" "$ROOT_DIR/code-cli/AGENTS.md"; then
  fail "documentation references retired skill names"
fi

for intent in exploration explanation planning building review knowledge; do
  grep -Fi "$intent" "$ROOT_DIR/README.md" >/dev/null || fail "root examples omit $intent"
done

# The vendoring apparatus is retired: each skill owns its own flat references,
# so no document may still instruct a reader to sync or edit a shared source.
if rg -n '_shared|sync-worktree-guidance|sync-code-cli-guidance|sync-shared-refs' \
  "$ROOT_DIR/AGENTS.md" "$SKILLS_DIR/README.md" "$ROOT_DIR/code-cli/AGENTS.md"; then
  fail "documentation still describes the retired vendoring apparatus"
fi
