#!/usr/bin/env bash
# Remove a worktree and its branch after merge or abandonment.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: cleanup.sh <id>

Force-removes the worktree for <id> and deletes worktree/<id>. Only call
this after merge.sh exits 0, or when deliberately abandoning the worktree's
work — it does not check for unmerged commits first.

Exit codes:
  0  removed (or already absent)
  1  usage error
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 1
fi

id="$1"
branch="worktree/${id}"
repo_name="$(basename "$(git rev-parse --show-toplevel)")"
repo_root="$(git rev-parse --show-toplevel)"
worktree_path="$(dirname "${repo_root}")/${repo_name}-worktrees/${id}"

git worktree remove "${worktree_path}" --force 2>/dev/null || true
git branch -D "${branch}" 2>/dev/null || true

if git worktree list --porcelain | grep -qx "worktree ${worktree_path}"; then
  echo "error: ${worktree_path} still present after removal attempt" >&2
  exit 1
fi

echo "removed worktree and branch for ${id}"
