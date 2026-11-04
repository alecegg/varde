#!/usr/bin/env bash
# Remove a registered worktree and its branch after merge or explicit discard.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: worktree-cleanup.sh [--discard] [--in-use <path>]... <id>

Removes the registered worktree on branch worktree/<id> or <branch> and deletes
that branch. Normal cleanup requires a worktree with no uncommitted files whose
branch is merged into the currently checked-out commit. Ignored files of any
name are listed and removed with the worktree. Use --discard only when
deliberately abandoning its committed or local work. Refuses if a process has
an open file in the worktree or if any --in-use path is inside it.

Exit codes:
  0  worktree and branch removed
  1  usage error or cleanup could not be completed safely
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

claude_probes=()
claude_probe_count=0
cleanup_claude_probes() {
  local status=$?
  local probe
  local cleanup_failed=false
  trap - EXIT
  if [[ "$claude_probe_count" -gt 0 ]]; then
    for probe in "${claude_probes[@]}"; do
      if ! rm -f "$probe"; then
        echo "error: could not remove .claude preflight probe ${probe}; rerun with escalated access" >&2
        cleanup_failed=true
      fi
    done
  fi
  [[ "$cleanup_failed" != true ]] || exit 1
  exit "$status"
}

preflight_claude_cleanup() {
  local claude_path directory file probe

  trap cleanup_claude_probes EXIT
  while IFS= read -r -d '' claude_path; do
    while IFS= read -r -d '' directory; do
      probe="$(mktemp "${directory%/}/.varde-worktree-cleanup-probe.XXXXXX" 2>/dev/null)" ||
        fail "cannot write to .claude directory ${directory}; rerun with escalated access"
      claude_probes+=("$probe")
      claude_probe_count=$((claude_probe_count + 1))
      rm -f "$probe" ||
        fail "cannot remove .claude preflight probe ${probe}; rerun with escalated access"
    done < <(find -P "$claude_path" -type d -print0)

    while IFS= read -r -d '' file; do
      : >> "$file" || fail "cannot write to .claude file ${file}; rerun with escalated access"
    done < <(find -P "$claude_path" -type f -print0)
  done < <(find -P "$target_path" -type d -name .claude -print0)
}

preflight_git_admin_dir() {
  local admin_dir admin_parent probe

  admin_dir="$(git -C "$target_path" rev-parse --path-format=absolute --git-dir 2>/dev/null)" ||
    fail "could not determine git admin dir for worktree ${id}"
  admin_parent="$(dirname "$admin_dir")"
  [[ -w "$admin_parent" ]] ||
    fail "cannot write to git admin parent dir ${admin_parent}; refusing cleanup"
  probe="$(mktemp "${admin_dir%/}/.varde-worktree-cleanup-probe.XXXXXX" 2>/dev/null)" ||
    fail "cannot write to git admin dir ${admin_dir}; refusing cleanup"
  rm -f "$probe" ||
    fail "cannot remove git admin probe ${probe} in ${admin_dir}; refusing cleanup"
}

check_worktree_not_in_use() {
  local use_path use_realpath lsof_output lsof_status lsof_errors line_number

  for use_path in "${in_use_paths[@]}"; do
    [[ -n "$use_path" ]] || continue
    use_realpath="$(cd "$use_path" 2>/dev/null && pwd -P)" ||
      fail "cannot resolve in-use path ${use_path}; refusing cleanup"
    case "$use_realpath/" in
      "$target_realpath/"*) fail "worktree ${id} is in use by ${use_path}" ;;
    esac
  done

  command -v lsof >/dev/null 2>&1 || fail "lsof is unavailable; cannot verify whether worktree ${id} is in use"
  lsof_errors="$(mktemp "${TMPDIR:-/tmp}/varde-lsof-errors.XXXXXX")" ||
    fail "cannot create lsof diagnostic file; refusing cleanup"
  if lsof_output="$(lsof -nP +D "$target_realpath" 2>"$lsof_errors")"; then
    lsof_status=0
  else
    lsof_status=$?
  fi
  if [[ -s "$lsof_errors" ]]; then
    rm -f "$lsof_errors"
    fail "lsof could not completely inspect worktree ${id}; refusing cleanup"
  fi
  rm -f "$lsof_errors" || fail "could not remove lsof diagnostic file; refusing cleanup"

  line_number=0
  while IFS= read -r; do
    line_number=$((line_number + 1))
    [[ "$line_number" -eq 1 && "$REPLY" == COMMAND* ]] && continue
    [[ -n "$REPLY" ]] || continue
    fail "worktree ${id} is in use by a process"
  done <<< "$lsof_output"
  [[ "$lsof_status" -eq 0 || "$lsof_status" -eq 1 ]] ||
    fail "lsof exited ${lsof_status}; cannot verify whether worktree ${id} is in use"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

discard=false
ignored_entries=""
in_use_paths=("")
while [[ $# -gt 1 ]]; do
  case "$1" in
    --discard) discard=true; shift ;;
    --in-use)
      [[ $# -ge 3 && -n "$2" ]] || fail "--in-use requires a path"
      in_use_paths+=("$2")
      shift 2
      ;;
    *) break ;;
  esac
done

if [[ $# -ne 1 || "$1" == -* ]]; then
  usage >&2
  exit 1
fi

id="$1"
git check-ref-format "refs/heads/${id}" >/dev/null 2>&1 || fail "invalid worktree id or branch '${id}'"
plain_branch_ref="refs/heads/${id}"
task_branch_ref="refs/heads/worktree/${id}"
plain_exists=false
task_exists=false
git show-ref --verify --quiet "$plain_branch_ref" && plain_exists=true
git show-ref --verify --quiet "$task_branch_ref" && task_exists=true
[[ "$plain_exists" != true || "$task_exists" != true ]] || fail "both ${id} and worktree/${id} branches exist; refusing ambiguous cleanup"
[[ "$plain_exists" == true || "$task_exists" == true ]] || fail "branch ${id} or worktree/${id} does not exist"
if [[ "$task_exists" == true ]]; then
  branch="worktree/${id}"
  branch_ref="$task_branch_ref"
else
  branch="$id"
  branch_ref="$plain_branch_ref"
fi

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

check_worktree_not_in_use

if [[ "$discard" != true ]]; then
  worktree_status="$(git -C "$target_path" status --porcelain --untracked-files=all 2>/dev/null)" ||
    fail "registered worktree is unavailable: ${target_path}"
  [[ -z "$worktree_status" ]] || fail "worktree ${id} has uncommitted changes; use --discard only to abandon them"

  ignored_status="$(git -C "$target_path" status --porcelain --ignored=matching --untracked-files=normal 2>/dev/null)" ||
    fail "could not inspect ignored files in worktree ${id}"
  while IFS= read -r line; do
    [[ "$line" == "!! "* ]] || continue
    ignored_entries+="${line#!! }"$'\n'
  done <<< "$ignored_status"

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

preflight_git_admin_dir
preflight_claude_cleanup

if [[ -n "${ignored_entries:-}" ]]; then
  echo "removing ignored files: ${ignored_entries//$'\n'/ }"
fi

check_worktree_not_in_use

printf -v repo_arg '%q' "$target_path"
watch_output=""
if ! watch_output="$(varde setup watch --stop --remove-index --repo "$target_path" 2>&1)"; then
  # The index-removal message is expected when stopping a watcher for an absent repo index.
  if [[ "$watch_output" != *"no watcher lock found for this repo set"* || "$watch_output" == *"removing code index:"* ]]; then
    [[ -z "$watch_output" ]] || echo "$watch_output" >&2
    echo "warning: watcher stop or index removal failed; retry with: varde setup watch --stop --remove-index --repo ${repo_arg}" >&2
  fi
else
  [[ -z "$watch_output" ]] || echo "$watch_output"
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

if [[ "$discard" == true ]]; then
  git update-ref -d "$branch_ref" "$branch_oid" ||
    fail "worktree was removed, but branch ${branch} changed after preflight or could not be discarded"
else
  if git config --get "branch.${branch}.remote" >/dev/null 2>&1; then
    git branch --unset-upstream "$branch" ||
      fail "worktree was removed, but could not clear the upstream for ${branch} before safe deletion"
  fi
  current_branch_oid="$(git rev-parse --verify "$branch_ref" 2>/dev/null)" ||
    fail "worktree was removed, but branch ${branch} disappeared after preflight"
  [[ "$current_branch_oid" == "$branch_oid" ]] ||
    fail "worktree was removed, but branch ${branch} changed after preflight"
  git branch -d -- "$branch" ||
    fail "worktree was removed, but branch ${branch} changed after preflight or could not be deleted safely"
fi

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
