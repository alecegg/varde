#!/usr/bin/env bash
# Merge a worktree's branch back into the target branch.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: worktree-merge.sh <id> [into]

Merges worktree/<id> into <into> (default: the branch currently checked out
in this checkout). An explicit <into> must name that checked-out branch. Does
NOT commit on the caller's behalf — the worktree must be clean.

Exit codes:
  0  merged cleanly, worktree/<id> is now in <into>
  1  usage error
  2  worktree/<id> has no commits ahead of its base — nothing to merge
  3  merge conflict — resolve via references/build-worktree.md, then finish the
     merge manually; do NOT run worktree-cleanup.sh until it's resolved
  4  target rejected: branch/<id> is missing, <into> does not resolve, <into>
     does not name the currently checked-out branch, or the merge failed for
     a reason other than conflict
  5  worktree/<id> has uncommitted changes — the task did not complete;
     caller decides
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
branch="worktree/${id}"
into="${2:-$(git rev-parse --abbrev-ref HEAD)}"
current_ref="$(git symbolic-ref --quiet HEAD 2>/dev/null || true)"

if [[ $# -eq 2 ]]; then
  target_ref="$(git rev-parse --symbolic-full-name "${into}" 2>/dev/null || true)"
  if [[ -z "${current_ref}" || ( "${into}" != "HEAD" && "${target_ref}" != "${current_ref}" ) ]]; then
    echo "error: target ${into} is not the currently checked-out branch" >&2
    exit 4
  fi
fi

common_git_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
repo_root="$(dirname "${common_git_dir}")"
worktree_path="${repo_root}/.varde/worktrees/${id}"

git rev-parse --verify --quiet "${branch}^{commit}" >/dev/null || { echo "error: branch ${branch} does not exist" >&2; exit 4; }
git rev-parse --verify --quiet "${into}^{commit}" >/dev/null || { echo "error: target ${into} does not resolve" >&2; exit 4; }
if [[ -d "${worktree_path}" ]] && [[ -n "$(git -C "${worktree_path}" status --porcelain)" ]]; then
  echo "error: worktree/${id} has uncommitted changes — the task did not complete" >&2
  exit 5
fi

merge_base="$(git merge-base "${into}" "${branch}")"
if [[ "$(git rev-parse "${branch}")" == "${merge_base}" ]]; then
  echo "error: ${branch} has no commits ahead of ${into} — nothing to merge" >&2
  exit 2
fi

if git merge --no-ff --no-edit "${branch}"; then
  echo "merged ${branch} into ${into}"
  exit 0
else
  if ! git diff --name-only --diff-filter=U | grep -q .; then
    echo "error: merge failed without conflicts" >&2
    exit 4
  fi
  echo "conflict merging ${branch} into ${into} — see references/build-worktree.md" >&2
  exit 3
fi
