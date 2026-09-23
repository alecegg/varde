#!/usr/bin/env bash
# Run one conflict-free task wave and integrate it atomically.
set -uo pipefail

usage() {
  cat <<'EOF'
Usage: run-parallel-wave.sh <task-manifest> [--target-ref <ref>] [--worktree-root <dir>]

The manifest must include a worker_command for every task in its first wave and
wave_verification_command for the staging worktree. Parallel tasks must carry
exact impact resources resolved before this script starts. Workers commit their
own changes. A target ref advances only after staging verification succeeds.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

manifest="$1"
shift
target_ref=""
worktree_root=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-ref)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      target_ref="$2"
      shift 2
      ;;
    --worktree-root)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      worktree_root="$2"
      shift 2
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resolver="$script_dir/resolve-execution-wave.py"

json_empty_workers='[]'
json_empty_refs='[]'
workers_json="$json_empty_workers"
recovery_refs_json="$json_empty_refs"
ownership_json='{}'
run_dir=""
integration_branch=""
integration_worktree=""
base_sha=""
resolver_error_file="${TMPDIR:-/tmp}/varde-wave-resolver-$$.error"
trap 'rm -f "$resolver_error_file"' EXIT

fail_json() {
  local message="$1"
  jq -n \
    --arg error "$message" \
    --arg target_ref "$target_ref" \
    --arg target_before "$base_sha" \
    --argjson workers "$workers_json" \
    --argjson recovery_refs "$recovery_refs_json" \
    '{status:"failed", error:$error, target_ref:$target_ref,
      target_before:$target_before, workers:$workers,
      recovery_refs:$recovery_refs}'
  exit 1
}

if [[ ! -f "$manifest" ]]; then
  target_ref=""
  fail_json "task manifest does not exist: $manifest"
fi

if ! repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  fail_json "runner must execute inside a git worktree"
fi

if [[ -z "$target_ref" ]]; then
  if ! current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null)"; then
    fail_json "detached HEAD requires --target-ref"
  fi
  target_ref="refs/heads/$current_branch"
elif [[ "$target_ref" != refs/* ]]; then
  target_ref="refs/heads/$target_ref"
fi

if ! base_sha="$(git rev-parse --verify "${target_ref}^{commit}" 2>/dev/null)"; then
  fail_json "target ref does not resolve: $target_ref"
fi
if [[ -n "$(git -C "$repo_root" status --porcelain)" ]]; then
  fail_json "target checkout must be clean before parallel integration"
fi

repo_worktree_path="$(cd "$repo_root" && pwd -P)"
target_other_worktree=""
find_target_worktree_conflict() {
  local listed_path=""
  local line=""
  local listed_realpath=""
  target_other_worktree=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        listed_path="${line#worktree }"
        ;;
      "branch "*)
        if [[ "${line#branch }" == "$target_ref" && -n "$listed_path" ]]; then
          if [[ -d "$listed_path" ]]; then
            listed_realpath="$(cd "$listed_path" && pwd -P)"
          else
            listed_realpath="$listed_path"
          fi
          if [[ "$listed_realpath" != "$repo_worktree_path" ]]; then
            target_other_worktree="$listed_path"
          fi
        fi
        ;;
    esac
  done < <(git -C "$repo_root" worktree list --porcelain)
  [[ -z "$target_other_worktree" ]]
}

if ! find_target_worktree_conflict; then
  fail_json "target ref is checked out in another linked worktree: $target_other_worktree"
fi

if ! wave_json="$(python3 "$resolver" "$manifest" 2>"$resolver_error_file")"; then
  resolver_error="$(sed -n '1p' "$resolver_error_file")"
  fail_json "task manifest cannot produce a valid execution wave: $resolver_error"
fi
if [[ "$(jq -r '.parallel_safe' <<< "$wave_json")" != true ]]; then
  if [[ "$(jq -r '.unknown_impact | length' <<< "$wave_json")" -gt 0 ]]; then
    fail_json "parallel wave requires complete impact evidence"
  fi
  fail_json "parallel wave requires complete, conflict-free ownership"
fi
if ! ownership_json="$(python3 - "$manifest" <<'PY'
import json
import posixpath
import sys

manifest_path = sys.argv[1]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)

def normalize(path):
    return posixpath.normpath(path.replace("\\", "/"))

owners = {}
for task in manifest["tasks"]:
    paths = []
    paths.extend(task.get("modifies", []))
    paths.extend(task.get("creates", []))
    for rename in task.get("renames", []):
        if isinstance(rename, dict):
            paths.extend(rename[key] for key in ("from", "to") if key in rename)
        else:
            paths.append(rename)
    owners[task["id"]] = sorted({normalize(path) for path in paths})

print(json.dumps(owners, separators=(",", ":")))
PY
)"; then
  fail_json "task manifest ownership cannot be normalized"
fi
task_ids=()
while IFS= read -r task_id; do
  task_ids+=("$task_id")
done < <(jq -r '.waves[0][]' <<< "$wave_json")
if [[ "${#task_ids[@]}" -lt 2 ]]; then
  fail_json "parallel wave requires at least two ready tasks"
fi

verification_command="$(jq -r '.wave_verification_command // empty' "$manifest")"
if [[ -z "$verification_command" ]]; then
  fail_json "manifest needs wave_verification_command"
fi

if [[ -z "$worktree_root" ]]; then
  worktree_root="${TMPDIR:-/tmp}/varde-parallel-waves"
fi
mkdir -p "$worktree_root" || fail_json "cannot create worktree root: $worktree_root"
run_id="$(date -u +%Y%m%d%H%M%S)-$$"
run_dir="$worktree_root/$run_id"
mkdir -p "$run_dir" || fail_json "cannot create run directory: $run_dir"
integration_branch="refs/heads/varde/parallel/${run_id}-integration"
integration_worktree="$run_dir/integration"
recovery_prefix="refs/varde/recovery/$run_id"

worker_paths=()
worker_branches=()
worker_pids=()
worker_result_files=()

retain_worker_recovery_refs() {
  local index worker_commit recovery_ref
  for index in "${!worker_branches[@]}"; do
    worker_commit="$(git rev-parse --verify "${worker_branches[$index]}" 2>/dev/null || printf '%s' "$base_sha")"
    recovery_ref="$recovery_prefix/workers/${task_ids[$index]}"
    git update-ref "$recovery_ref" "$worker_commit"
    recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  done
}

scope_escape_path=""
worker_scope_is_declared() {
  local task_id="$1"
  local commit="$2"
  local owned_paths_json
  local changed_path
  local owned_path
  local declared=false
  scope_escape_path=""
  owned_paths_json="$(jq -c --arg id "$task_id" '.[$id] // []' <<< "$ownership_json")"
  while IFS= read -r -d '' changed_path; do
    declared=false
    while IFS= read -r owned_path; do
      if [[ "$changed_path" == "$owned_path" || "$changed_path" == "$owned_path/"* ]]; then
        declared=true
        break
      fi
    done < <(jq -r '.[]' <<< "$owned_paths_json")
    if [[ "$declared" != true ]]; then
      scope_escape_path="$changed_path"
      return 1
    fi
  done < <(git diff --no-renames --name-only -z "$base_sha" "$commit" --)
  return 0
}

timestamp_ms() {
  python3 -c 'import time; print(int(time.time() * 1000))'
}

for task_id in "${task_ids[@]}"; do
  case "$task_id" in
    ''|*[!A-Za-z0-9._-]*)
      fail_json "task id is not safe for isolated worktree names: $task_id"
      ;;
  esac
  worker_command="$(jq -r --arg id "$task_id" '.tasks[] | select(.id == $id) | .worker_command // empty' "$manifest")"
  [[ -n "$worker_command" ]] || fail_json "task $task_id needs worker_command"

  worker_path="$run_dir/$task_id"
  worker_branch="refs/heads/varde/parallel/${run_id}-${task_id}"
  if ! git worktree add --quiet -b "${worker_branch#refs/heads/}" "$worker_path" "$base_sha"; then
    fail_json "cannot create isolated worktree for task $task_id"
  fi
  worker_paths+=("$worker_path")
  worker_branches+=("$worker_branch")
  result_file="$run_dir/$task_id.result"
  worker_result_files+=("$result_file")
  (
    started_at_ms="$(timestamp_ms)"
    if (cd "$worker_path" && VARDE_TASK_ID="$task_id" VARDE_WORKTREE="$worker_path" bash -c "$worker_command") \
      >"$run_dir/$task_id.log" 2>&1; then
      status=0
    else
      status=$?
    fi
    ended_at_ms="$(timestamp_ms)"
    printf '%s\t%s\t%s\t%s\n' "$task_id" "$status" "$started_at_ms" "$ended_at_ms" > "$result_file"
  ) &
  worker_pids+=("$!")
done

for pid in "${worker_pids[@]}"; do
  wait "$pid" || true
done

for result_file in "${worker_result_files[@]}"; do
  if [[ ! -s "$result_file" ]]; then
    fail_json "worker did not report completion"
  fi
  IFS=$'\t' read -r task_id status started_at_ms ended_at_ms < "$result_file"
  branch_index=0
  for candidate in "${task_ids[@]}"; do
    [[ "$candidate" == "$task_id" ]] && break
    branch_index=$((branch_index + 1))
  done
  branch="${worker_branches[$branch_index]}"
  commit="$(git rev-parse --verify "$branch" 2>/dev/null || true)"
  if [[ -z "$commit" ]]; then
    commit="$base_sha"
  fi
  workers_json="$(jq -c \
    --arg id "$task_id" \
    --arg path "${worker_paths[$branch_index]}" \
    --arg branch "$branch" \
    --arg commit "$commit" \
    --argjson status "$status" \
    --argjson started "$started_at_ms" \
    --argjson ended "$ended_at_ms" \
    '. + [{id:$id, worktree:$path, branch:$branch, commit:$commit,
      exit_status:$status, started_at_ms:$started, ended_at_ms:$ended}]' <<< "$workers_json")"
  if [[ "$status" != 0 || "$commit" == "$base_sha" ]]; then
    retain_worker_recovery_refs
    fail_json "worker $task_id failed or produced no commit"
  fi
  if [[ -n "$(git -C "${worker_paths[$branch_index]}" status --porcelain)" ]]; then
    retain_worker_recovery_refs
    fail_json "worker $task_id left uncommitted changes"
  fi
  owned_paths=()
  while IFS= read -r owned_path; do
    owned_paths+=("$owned_path")
  done < <(jq -r --arg id "$task_id" '
    .tasks[] | select(.id == $id) |
    [
      ((.modifies // [])[]),
      ((.creates // [])[]),
      ((.renames // [])[] |
        if type == "object" then (.from // empty), (.to // empty) else . end)
    ] | unique[]
  ' "$manifest")
  if [[ "${#owned_paths[@]}" -gt 0 ]] &&
      [[ -n "$(git -C "${worker_paths[$branch_index]}" status --porcelain --ignored -- "${owned_paths[@]}")" ]]; then
    retain_worker_recovery_refs
    fail_json "worker $task_id left uncommitted changes"
  fi
  if ! worker_scope_is_declared "$task_id" "$commit"; then
    retain_worker_recovery_refs
    fail_json "worker $task_id committed undeclared path: $scope_escape_path"
  fi
done

if ! git branch "${integration_branch#refs/heads/}" "$base_sha" >/dev/null 2>&1; then
  fail_json "cannot create integration branch"
fi
if ! git worktree add --quiet "$integration_worktree" "${integration_branch#refs/heads/}"; then
  fail_json "cannot create integration worktree"
fi

for branch in "${worker_branches[@]}"; do
  if ! git -C "$integration_worktree" merge --no-ff --no-edit "$branch" >/dev/null 2>&1; then
    git -C "$integration_worktree" merge --abort >/dev/null 2>&1 || true
    integration_sha="$(git rev-parse --verify "$integration_branch")"
    recovery_ref="$recovery_prefix/integration"
    git update-ref "$recovery_ref" "$integration_sha"
    recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
    retain_worker_recovery_refs
    fail_json "wave integration merge failed"
  fi
done

integration_sha_before_verification="$(git rev-parse --verify "$integration_branch")"
if ! (cd "$integration_worktree" && bash -c "$verification_command") \
  >"$run_dir/verification.log" 2>&1; then
  integration_sha="$(git rev-parse --verify "$integration_branch")"
  recovery_ref="$recovery_prefix/integration"
  git update-ref "$recovery_ref" "$integration_sha"
  recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  retain_worker_recovery_refs
  fail_json "wave verification failed"
fi

integration_sha_after_verification="$(git rev-parse --verify "$integration_branch")"
if [[ "$integration_sha_after_verification" != "$integration_sha_before_verification" ||
      -n "$(git -C "$integration_worktree" status --porcelain --untracked-files=all --ignored)" ]]; then
  integration_sha="$integration_sha_after_verification"
  recovery_ref="$recovery_prefix/integration"
  git update-ref "$recovery_ref" "$integration_sha"
  recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  retain_worker_recovery_refs
  fail_json "wave verification mutated the staging worktree"
fi

integration_sha="$integration_sha_before_verification"
if ! find_target_worktree_conflict; then
  recovery_ref="$recovery_prefix/integration"
  git update-ref "$recovery_ref" "$integration_sha"
  recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  retain_worker_recovery_refs
  fail_json "target ref is checked out in another linked worktree: $target_other_worktree"
fi
current_ref="$(git -C "$repo_root" symbolic-ref --quiet HEAD 2>/dev/null || true)"
checkout_changed=false
if [[ "$current_ref" == "$target_ref" ]]; then
  if [[ -n "$(git -C "$repo_root" status --porcelain)" ]]; then
    checkout_changed=true
  else
    while IFS= read -r -d '' added_path; do
      if [[ -e "$repo_root/$added_path" || -L "$repo_root/$added_path" ]]; then
        checkout_changed=true
        break
      fi
    done < <(git diff --no-renames --diff-filter=A --name-only -z "$base_sha" "$integration_sha" --)
  fi
fi
if [[ "$checkout_changed" == true ]]; then
  recovery_ref="$recovery_prefix/integration"
  git update-ref "$recovery_ref" "$integration_sha"
  recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  retain_worker_recovery_refs
  fail_json "target checkout changed during integration"
fi
if ! git update-ref "$target_ref" "$integration_sha" "$base_sha"; then
  recovery_ref="$recovery_prefix/integration"
  git update-ref "$recovery_ref" "$integration_sha"
  recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  fail_json "target ref changed during integration"
fi
if [[ "$current_ref" == "$target_ref" ]] &&
    ! git -C "$repo_root" read-tree -u -m "$base_sha" "$integration_sha"; then
  git update-ref "$target_ref" "$base_sha" "$integration_sha" >/dev/null 2>&1 || true
  recovery_ref="$recovery_prefix/integration"
  git update-ref "$recovery_ref" "$integration_sha"
  recovery_refs_json="$(jq -c --arg ref "$recovery_ref" '. + [$ref]' <<< "$recovery_refs_json")"
  fail_json "target checkout could not synchronize after integration"
fi

for path in "${worker_paths[@]}" "$integration_worktree"; do
  git worktree remove --force "$path" >/dev/null 2>&1 || true
done
for branch in "${worker_branches[@]}" "$integration_branch"; do
  git branch -D "${branch#refs/heads/}" >/dev/null 2>&1 || true
done

jq -n \
  --arg target_ref "$target_ref" \
  --arg target_before "$base_sha" \
  --arg target_after "$integration_sha" \
  --argjson workers "$workers_json" \
  '{status:"integrated", target_ref:$target_ref, target_before:$target_before,
    target_after:$target_after, workers:$workers, recovery_refs:[]}'
