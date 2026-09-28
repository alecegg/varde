#!/usr/bin/env bash
# Remove a registered worktree and its branch after merge or explicit discard.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: worktree-cleanup.sh [--discard] <id>

Removes the registered worktree on branch worktree/<id> and deletes that
branch. Normal cleanup requires a worktree with no uncommitted or ignored
files whose branch is merged into the currently checked-out commit. Use
--discard only when deliberately abandoning its committed or local work.

Exit codes:
  0  worktree and branch removed
  1  usage error or cleanup could not be completed safely
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

discard=false
if [[ "${1:-}" == "--discard" ]]; then
  discard=true
  shift
fi

if [[ $# -ne 1 || "$1" == -* ]]; then
  usage >&2
  exit 1
fi

id="$1"
branch="worktree/${id}"
branch_ref="refs/heads/${branch}"
git check-ref-format "$branch_ref" >/dev/null 2>&1 || fail "invalid worktree id '${id}'"

git rev-parse --path-format=absolute --git-common-dir >/dev/null 2>&1 ||
  fail "not inside a Git worktree"
git show-ref --verify --quiet "$branch_ref" || fail "branch ${branch} does not exist"
branch_oid="$(git rev-parse --verify "$branch_ref")" || fail "could not resolve branch ${branch}"

# Resolve by the branch recorded by Git, not by a path inferred from the
# current checkout. The caller may be in the main checkout or any linked tree.
registry="$(git worktree list --porcelain)" || fail "could not list registered worktrees"
target_path=""
record_path=""
record_branch=""
matches=0

record_target_if_matching() {
  if [[ -n "$record_path" && "$record_branch" == "$branch_ref" ]]; then
    matches=$((matches + 1))
    target_path="$record_path"
  fi
}

while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    "worktree "*)
      record_target_if_matching
      record_path="${line#worktree }"
      record_branch=""
      ;;
    "branch "*)
      record_branch="${line#branch }"
      ;;
    "")
      record_target_if_matching
      record_path=""
      record_branch=""
      ;;
  esac
done <<< "$registry"
record_target_if_matching

[[ "$matches" -eq 1 ]] || {
  if [[ "$matches" -eq 0 ]]; then
    fail "no registered worktree uses branch ${branch}"
  fi
  fail "multiple registered worktrees use branch ${branch}; refusing cleanup"
}

[[ -d "$target_path" ]] || fail "registered worktree path is unavailable: ${target_path}"
target_realpath="$(cd "$target_path" && pwd -P)" ||
  fail "registered worktree path is unavailable: ${target_path}"
caller_realpath="$(pwd -P)"
case "$caller_realpath/" in
  "$target_realpath/"*) fail "cannot clean up the worktree that contains the current directory" ;;
esac

if [[ "$discard" != true ]]; then
  worktree_status="$(git -C "$target_path" status --porcelain --untracked-files=all 2>/dev/null)" ||
    fail "registered worktree is unavailable: ${target_path}"
  [[ -z "$worktree_status" ]] || fail "worktree ${id} has uncommitted changes; use --discard only to abandon them"

  ignored_status="$(git -C "$target_path" status --porcelain --untracked-files=all --ignored 2>/dev/null)" ||
    fail "could not inspect ignored files in worktree ${id}"
  [[ -z "$ignored_status" ]] || fail "worktree ${id} has ignored files; use --discard only to abandon them"

  if git merge-base --is-ancestor "$branch_oid" HEAD; then
    :
  else
    merge_status=$?
    if [[ "$merge_status" -eq 1 ]]; then
      fail "branch ${branch} is not merged into the currently checked-out commit; use --discard only to abandon it"
    fi
    fail "could not verify whether branch ${branch} is merged"
  fi
fi

if [[ "$discard" == true ]]; then
  git worktree remove --force "$target_path" || fail "could not discard worktree ${target_path}"
else
  git worktree remove "$target_path" || fail "could not remove clean worktree ${target_path}"
fi

remaining_registry="$(git worktree list --porcelain)" || fail "could not verify worktree removal"
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" == "worktree ${target_path}" ]]; then
    fail "worktree ${target_path} remains registered after removal"
  fi
done <<< "$remaining_registry"

git update-ref -d "$branch_ref" "$branch_oid" ||
  fail "worktree was removed, but branch ${branch} changed after preflight or could not be deleted safely"

if git show-ref --verify --quiet "$branch_ref"; then
  fail "branch ${branch} remains after removal"
else
  show_ref_status=$?
  [[ "$show_ref_status" -eq 1 ]] || fail "could not verify branch removal for ${branch}"
fi

if [[ "$discard" == true ]]; then
  echo "discarded worktree and branch for ${id}"
else
  echo "removed worktree and branch for ${id}"
fi
