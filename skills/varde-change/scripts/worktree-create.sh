#!/usr/bin/env bash
# Create an isolated git worktree pinned to a fixed base SHA.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: create.sh <id> [base]

Creates a worktree for <id> at ../<repo-name>-worktrees/<id>, branched from
<base> (default: HEAD), pinned to that commit's resolved SHA.

Prints three lines on success:
  path=<worktree-path>
  branch=<branch>
  created=<true|false>

created=true  a fresh worktree was made and the caller OWNS it — the caller
              must merge + cleanup when done.
created=false the caller is already inside a linked worktree, so this is a
              no-op that reuses it; the caller must NOT merge or cleanup
              (whoever created the outer worktree owns that).

Exit codes:
  0  worktree created, or reused because already inside a linked worktree
  1  usage error
  2  <base> did not resolve to a commit
  3  a worktree or branch for <id> already exists
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage >&2
  exit 1
fi

id="$1"
base="${2:-HEAD}"

base_sha="$(git rev-parse --verify "${base}^{commit}" 2>/dev/null)" || {
  echo "error: base '${base}' did not resolve to a commit" >&2
  exit 2
}

# Already inside a linked worktree? Then the caller is already isolated —
# reuse it instead of nesting a second worktree. --git-dir and --git-common-dir
# diverge only inside a linked worktree; they're identical in the main checkout.
if [[ "$(git rev-parse --git-dir)" != "$(git rev-parse --git-common-dir)" ]]; then
  echo "note: already inside a linked worktree — reusing it, no new worktree created" >&2
  echo "path=$(git rev-parse --show-toplevel)"
  echo "branch=$(git rev-parse --abbrev-ref HEAD)"
  echo "created=false"
  exit 0
fi

repo_name="$(basename "$(git rev-parse --show-toplevel)")"
repo_root="$(git rev-parse --show-toplevel)"
worktree_path="$(dirname "${repo_root}")/${repo_name}-worktrees/${id}"
branch="worktree/${id}"

if git worktree list --porcelain | grep -qx "worktree ${worktree_path}"; then
  echo "error: worktree already exists at ${worktree_path}" >&2
  exit 3
fi
if git show-ref --verify --quiet "refs/heads/${branch}"; then
  echo "error: branch ${branch} already exists" >&2
  exit 3
fi

mkdir -p "$(dirname "${worktree_path}")"
git worktree add -b "${branch}" "${worktree_path}" "${base_sha}" >&2

echo "path=${worktree_path}"
echo "branch=${branch}"
echo "created=true"
