#!/usr/bin/env bash
# Create an isolated git worktree pinned to a fixed base SHA.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: worktree-create.sh [--fresh] <id> [base]
       worktree-create.sh --plan <id> <explicit-base>

Creates a worktree for <id> at <repo>/.varde/worktrees/<id>, branched from
<base> (default: HEAD), pinned to that commit's resolved SHA. New worktrees
require a clean, committed caller. --fresh allocates a sibling even inside
a linked worktree; without it, a linked caller keeps ownership and is reused.
--plan always creates a fresh plan worktree at an explicit committed base;
it permits a dirty origin and leaves its branch, index and local files intact.

Prints on success:
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
  4  caller is dirty, detached, or has no committed HEAD
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

fresh=false
plan=false
case "${1:-}" in
  --fresh) fresh=true; shift ;;
  --plan) fresh=true; plan=true; shift ;;
esac
if [[ $# -lt 1 || $# -gt 2 || "${1:-}" == -* || "${2:-}" == --plan || "${2:-}" == --fresh ]] ||
   { [[ "$plan" == true ]] && [[ $# -ne 2 || -z "${2:-}" ]]; }; then
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
if [[ "$fresh" == false && "$(git rev-parse --git-dir)" != "$(git rev-parse --git-common-dir)" ]]; then
  echo "note: already inside a linked worktree — reusing it, no new worktree created" >&2
  echo "path=$(git rev-parse --show-toplevel)"
  echo "branch=$(git rev-parse --abbrev-ref HEAD)"
  echo "created=false"
  exit 0
fi

repo_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
worktree_path="${repo_root}/.varde/worktrees/${id}"
branch="worktree/${id}"

if git worktree list --porcelain | grep -x "worktree ${worktree_path}" >/dev/null; then
  echo "error: worktree already exists at ${worktree_path}" >&2
  exit 3
fi
if git show-ref --verify --quiet "refs/heads/${branch}"; then
  echo "error: branch ${branch} already exists" >&2
  exit 3
fi

git check-ref-format "refs/heads/$branch" >/dev/null || { echo "error: invalid worktree id '${id}'" >&2; exit 1; }
if [[ "$plan" == false ]] && {
   [[ -n "$(git status --porcelain)" ]] ||
   ! git symbolic-ref --quiet HEAD >/dev/null ||
   ! git rev-parse --verify HEAD >/dev/null 2>&1;
}; then
  echo "error: caller must be clean and on a committed branch" >&2
  exit 4
fi
mkdir -p "$(dirname "${worktree_path}")"
# Keep the nested worktrees out of the main checkout's status without editing
# any tracked .gitignore.
exclude="$(git rev-parse --path-format=absolute --git-common-dir)/info/exclude"
mkdir -p "$(dirname "${exclude}")"
grep -qx '/.varde/' "${exclude}" 2>/dev/null || echo '/.varde/' >> "${exclude}"
git worktree add -b "${branch}" "${worktree_path}" "${base_sha}" >&2

echo "path=${worktree_path}"
echo "branch=${branch}"
echo "created=true"
