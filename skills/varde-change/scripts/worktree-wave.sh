#!/usr/bin/env bash
# Run the deterministic steps of a worktree wave: start, integrate, release.
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage:
  worktree-wave.sh start <wave-id> <task-id>... --task <task-id>=<abs-task-file>...
  worktree-wave.sh integrate <wave-id> --check <command>
  worktree-wave.sh release <wave-id> [--keep]

Run from the clean, committed plan worktree (the plan branch is the target).
Start creates one worktree and branch per task. Integrate audits each task
commit against its task file, merges the workers in task-id order, runs one
combined check, bisects a failure to the culprit task, then fast-forwards the
plan branch. Release removes the task and integration worktrees.

start      Records the plan worktree, branch, HEAD and task files, then creates
           a fresh sibling worktree and branch per task. Rerun an unfinished
           start with the same arguments to resume.
integrate  Runs check-task-ownership on every task commit, syncs behind workers
           with the queue tip, fast-forwards the queue, then runs the combined
           check once. On failure it bisects task prefixes and exits 5 with
           culprit=<task>, verified_prefix=<commit> and
           untouched_remainder=<tasks>. On success it fast-forwards the plan
           branch and prints verified_commit.
release    Removes the task and integration worktrees and their branches.
           With --keep, clean task worktrees enter the bounded pool.
           Ignored files of any name are removed with the worktree; tracked
           and untracked changes still block cleanup.

Exit codes:
  0  success
  1  usage error or pending cleanup step
  3  sync conflict (conflict_in=<task> paths=<paths>) or unresolved
     integration merge (conflict_in=integration paths=<paths>)
  4  dirty, moved, detached or missing checkout/ref; non-plan target
  5  failed task or combined check; integrate reports culprit=<task>,
     verified_prefix=<commit> and untouched_remainder=<tasks>
  6  could not acquire the repository integration-check lock before timeout

EOF2
}

die() { echo "error: $1" >&2; exit "${2:-1}"; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$(basename "$0")"

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }
[[ $# -ge 2 ]] || { usage >&2; exit 1; }
cmd="$1"; shift
if [[ "$cmd" == release ]]; then
  [[ ( $# -eq 1 || ( $# -eq 2 && "$2" == --keep ) ) && "$1" != -* ]] || { usage >&2; exit 1; }
  wave="$1"
  keep=false
  [[ $# -eq 2 ]] && keep=true
  set --
else
  wave="${1:-}"
  [[ -n "$wave" ]] || { usage >&2; exit 1; }
  shift
fi
git check-ref-format "refs/heads/worktree/${wave}-integration" || die "invalid wave id '${wave}'"

common="$(git rev-parse --path-format=absolute --git-common-dir)"
repo="$(dirname "$common")"
state="$common/varde-waves/$wave"
integration="${wave}-integration"
iw="$repo/.varde/worktrees/$integration"

state_all() { sed -n "s/^$1=//p" "$state"; }
state_get() { state_all "$1" | tail -n 1; }
branch_exists() { git show-ref --verify --quiet "refs/heads/$1"; }

load_state() {
  [[ -f "$state" ]] || die "no recorded wave '${wave}'; run start first"
  approval="$(state_get approval)"
  [[ "$(cd "$(git rev-parse --show-toplevel)" && pwd -P)" == "$approval" ]] || die "run from plan worktree ${approval}" 4
  [[ "$(state_get queue_version)" == 3 ]] \
    || die "wave ${wave} has legacy state; restart with: ${SELF} start <new-wave-id> <task-id>... --task <task-id>=<task.md>" 4
  target="$(state_get target)" base="$(state_get base)" tasks="$(state_get tasks)"
  target_base="$(state_get target_base)"
  [[ -n "$target_base" ]] || target_base="$base"
  [[ "$(git symbolic-ref --quiet --short HEAD)" == "$target" ]] || die "run from the target branch ${target}" 4
}

require_plan_target() {
  [[ "$target" == worktree/* ]] \
    || die "integrate fast-forwards only a plan branch; merge ${target} with worktree-merge.sh after user approval" 4
  [[ "$approval" == "$repo/.varde/worktrees/${target#worktree/}" ]] \
    || die "run from the plan worktree that owns ${target}" 4
}

# Create (or reuse) one task's worktree. Run in an `if`, so each step returns
# explicitly.
provision() {
  local id="$1" out worker_path
  worker_path="$repo/.varde/worktrees/$id"
  if ! branch_exists "worktree/$id"; then
    if ! take_from_pool "$id"; then
      out="$("$HERE/worktree-create.sh" --fresh "$id" "$base")" || return 1
      worker_path="$(sed -n 's/^path=//p' <<<"$out")"
    fi
  fi
  [[ -d "$worker_path" && "$(git -C "$worker_path" symbolic-ref --quiet --short HEAD)" == "worktree/$id" && "$(git -C "$worker_path" rev-parse HEAD)" == "$base" && -z "$(git -C "$worker_path" status --porcelain)" ]] || {
    echo "error: existing worker ${id} is not clean at the recorded base" >&2
    return 1
  }
  echo "provisioned=$id" >> "$state"
  echo "task=$id worktree=$worker_path branch=worktree/$id"
}

take_from_pool() {
  local id="$1" pool="$repo/.varde/worktrees/pool" candidate next="$repo/.varde/worktrees/$1"
  [[ -d "$pool" ]] || return 1
  candidate="$(find "$pool" -mindepth 1 -maxdepth 1 -type d -print | sort | head -n 1)"
  [[ -n "$candidate" ]] || return 1
  git worktree move "$candidate" "$next" >&2 || return 1
  git -C "$next" reset --hard "$base" >/dev/null || return 1
  git -C "$next" checkout -B "worktree/$id" "$base" >/dev/null || return 1
  rmdir "$pool" 2>/dev/null || true
  echo "reused pooled worktree for $id"
}

task_file_for() {
  local id="$1" file
  for file in "${files[@]:-}"; do
    if [[ "$file" == "${id}="* ]]; then
      printf '%s' "${file#*=}"
      return 0
    fi
  done
  return 1
}

start() {
  local id target base sorted approval
  local ids=() files=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --task) files+=("${2:?--task needs task=file}"); shift 2 ;;
      -*) usage >&2; exit 1 ;;
      *) ids+=("$1"); shift ;;
    esac
  done
  [[ ${#ids[@]} -gt 0 ]] || { usage >&2; exit 1; }
  for id in "${ids[@]}"; do
    [[ "$id" != pool ]] || die "task id pool is reserved"
    local task_file
    task_file="$(task_file_for "$id" || true)"
    [[ -n "$task_file" ]] || die "task ${id} needs --task ${id}=<task.md>"
    [[ "$task_file" == /* && -f "$task_file" ]] || die "task file for ${id} must be an existing absolute path: ${task_file}"
  done

  approval="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
  sorted="$(printf '%s\n' "${ids[@]}" | sort | tr '\n' ' ' | sed 's/ $//')"
  if [[ -f "$state" ]]; then
    [[ "$(state_get queue_version)" == 3 ]] \
      || die "wave ${wave} has legacy state; restart with: ${SELF} start <new-wave-id> <task-id>... --task <task-id>=<task.md>" 4
    [[ "$(state_get tasks)" == "$sorted" ]] || die "wave ${wave} was recorded with a different task list"
    [[ "$(state_get approval)" == "$approval" ]] || die "run from recorded plan worktree" 4
    [[ -z "$(state_get started)" ]] || die "wave ${wave} already started"
    target="$(state_get target)" base="$(state_get base)"
    [[ "$(git symbolic-ref --quiet --short HEAD)" == "$target" && "$(git rev-parse HEAD)" == "$base" && -z "$(git status --porcelain)" ]] || die "plan worktree is dirty, moved or on another branch" 4
    for id in "${ids[@]}"; do
      [[ "$(state_get "task_file.$id")" == "$(task_file_for "$id")" ]] \
        || die "wave ${wave} was recorded with a different task file for ${id}"
    done
  else
    [[ -z "$(git status --porcelain)" ]] || die "plan worktree is not clean" 4
    target="$(git symbolic-ref --quiet --short HEAD)" || die "plan worktree must be on the plan branch" 4
    base="$(git rev-parse --verify HEAD)" || die "plan worktree needs a committed HEAD" 4
    mkdir -p "$(dirname "$state")"
    printf 'queue_version=3\napproval=%s\ntarget=%s\nbase=%s\ntarget_base=%s\ntasks=%s\n' \
      "$approval" "$target" "$base" "$base" "$sorted" > "$state"
    for id in "${ids[@]}"; do
      printf 'task_file.%s=%s\n' "$id" "$(task_file_for "$id")" >> "$state"
    done
  fi

  for id in "${ids[@]}"; do
    if grep -qx "provisioned=$id" "$state"; then
      echo "skip $id (already provisioned)"
      continue
    fi
    if ! provision "$id"; then
      {
        echo "error: provisioning ${id} failed; wave state kept at ${state}"
        echo "provisioned so far: $(sed -n 's/^provisioned=//p' "$state" | tr '\n' ' ')"
        echo "next: fix the cause, then rerun the same '${SELF} start ${wave} ...' to resume"
        echo "to abandon: clean up created workers, then delete ${state}; restart with the same task ids"
      } >&2
      exit 1
    fi
  done
  echo "started=true" >> "$state"
}

# A verification record covers the exact integration tip and every worker tip.
verification_snapshot() {
  local id worker_path tip position=0 verify_count
  if [[ $# -gt 0 ]]; then
    verify_count="$1"
  else
    verify_count="$(wc -w <<<"$tasks" | tr -d ' ')"
  fi
  [[ -d "$iw" && "$(git -C "$iw" symbolic-ref --quiet --short HEAD)" == "worktree/$integration" && -z "$(git -C "$iw" status --porcelain)" ]] || return 1
  printf 'integration=%s\n' "$(git -C "$iw" rev-parse HEAD)"
  for id in $tasks; do
    position=$((position + 1))
    worker_path="$repo/.varde/worktrees/$id"
    [[ -d "$worker_path" && "$(git -C "$worker_path" symbolic-ref --quiet --short HEAD)" == "worktree/$id" && -z "$(git -C "$worker_path" status --porcelain)" ]] || return 1
    tip="$(git -C "$worker_path" rev-parse HEAD)" || return 1
    if (( position <= verify_count )) && [[ "$tip" != "$base" ]]; then
      git merge-base --is-ancestor "$base" "$tip" || return 1
      git -C "$iw" merge-base --is-ancestor "$tip" HEAD || return 1
    fi
    printf 'worker=%s=%s\n' "$id" "$tip"
  done
}

report_integration() {
  echo "worktree=$iw"
  echo "branch=worktree/$integration"
  echo "base=$base"
  echo "integration_base=$target_base"
  echo "verified_commit=$(git -C "$iw" rev-parse HEAD)"
}

check_task_commit() {
  local id="$1" worker_path="$2" task_file="$3" commit="$4" output_dir rc=0
  output_dir="$(mktemp -d "$(dirname "$state")/.ownership.XXXXXX")" \
    || die "could not capture ownership check output for ${id}" 5
  (cd "$worker_path" && varde plan check-task-ownership --task "$task_file" \
    --commit "$commit" --repo-root "$worker_path" --json) \
    >"$output_dir/stdout" 2>"$output_dir/stderr" || rc=$?
  if [[ "$rc" != 0 ]]; then
    [[ ! -s "$output_dir/stdout" ]] || cat "$output_dir/stdout" >&2
    [[ ! -s "$output_dir/stderr" ]] || cat "$output_dir/stderr" >&2
    rm -rf -- "$output_dir"
    die "task ${id} ownership check failed for commit ${commit}" 5
  fi
  rm -rf -- "$output_dir"
}

integrated_check_warning_emitted=false
run_integrated_check() {
  local check="$1"
  if [[ -f "$iw/clis/Cargo.toml" && ! -x "$iw/clis/target/debug/varde" && "$integrated_check_warning_emitted" == false ]]; then
    echo "warning: clis/target/debug/varde is missing; integrated check will use the installed varde" >&2
    integrated_check_warning_emitted=true
  fi
  (cd "$iw" && PATH="$iw/clis/target/debug:$iw/target/debug:$PATH" bash -c "$check")
}

acquire_integrate_lock() {
  local lock="$common/varde-waves/integrate.lock" wait_seconds="${VARDE_INTEGRATE_LOCK_WAIT:-1800}"
  local started now holder current stale lock_age lock_mtime
  [[ "$wait_seconds" =~ ^[0-9]+$ ]] || die "VARDE_INTEGRATE_LOCK_WAIT must be a non-negative integer"
  mkdir -p "$(dirname "$lock")"
  started="$(date +%s)"
  while ! mkdir "$lock" 2>/dev/null; do
    holder=""
    [[ -f "$lock/pid" ]] && holder="$(cat "$lock/pid" 2>/dev/null || true)"
    lock_mtime="$(stat -c %Y "$lock" 2>/dev/null || stat -f %m "$lock" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    lock_age=$((now - lock_mtime))
    stale=false
    if [[ "$holder" =~ ^[0-9]+$ ]]; then
      if kill -0 "$holder" 2>/dev/null || ps -p "$holder" -o pid= 2>/dev/null | grep -q '[0-9]'; then
        stale=false
      else
        stale=true
      fi
    elif [[ ! -e "$lock/pid" && "$lock_age" -ge 3 ]]; then
      stale=true
    fi
    if [[ "$stale" == true ]]; then
      current=""
      [[ -f "$lock/pid" ]] && current="$(cat "$lock/pid" 2>/dev/null || true)"
      if [[ "$current" == "$holder" ]]; then
        stale="${lock}.stale.$$"
        if mv "$lock" "$stale" 2>/dev/null; then rm -rf -- "$stale"; fi
      fi
      continue
    fi
    now="$(date +%s)"
    (( now - started < wait_seconds )) || die "timed out waiting for repository integration lock after ${wait_seconds}s" 6
    sleep 1
  done
  printf '%s\n' "$$" > "$lock/pid"
  integrate_lock="$lock"
  trap release_integrate_lock EXIT
}

release_integrate_lock() {
  if [[ -n "${integrate_lock:-}" && -f "$integrate_lock/pid" && "$(cat "$integrate_lock/pid" 2>/dev/null || true)" == "$$" ]]; then
    rm -rf -- "$integrate_lock"
  fi
  integrate_lock=""
}

run_measured_check() {
  local check="$1" output_file status_file status bytes
  output_file="$(mktemp)"
  status_file="$(mktemp)"
  (
    set +e
    cd "$iw" && "$HERE/measure-writes.sh" run --root "$iw" --label "wave:$wave" -- bash -c "$check" 2>&1 | tee "$output_file" /dev/stderr
    printf '%s\n' "${PIPESTATUS[0]}" > "$status_file"
  )
  status="$(cat "$status_file")"
  rm -f "$status_file"
  bytes="$(sed -n 's/^writes: bytes=\([0-9][0-9]*\).*/\1/p' "$output_file" | tail -n 1)"
  rm -f "$output_file"
  [[ "$bytes" =~ ^[0-9]+$ ]] || die "could not read measured check write bytes" 5
  printf 'check_write_bytes=%s\n' "$bytes" >> "$state"
  return "$status"
}

merge_workers() {
  local id tip worker_path task_file commit commits merge_head
  local queue_tip paths rc position=0 task_index=0 output_dir task_limit
  local -a conflicts=()
  task_limit="${1:-$(wc -w <<<"$tasks" | tr -d ' ')}"

  # Audit every task before changing any worker or the integration branch.
  for id in $tasks; do
    worker_path="$repo/.varde/worktrees/$id"
    [[ -d "$worker_path" ]] || die "task ${id} has a missing worktree" 5
    [[ "$(git -C "$worker_path" symbolic-ref --quiet --short HEAD)" == "worktree/$id" ]] \
      || die "worker ${id} is on another branch" 4
    tip="$(git -C "$worker_path" rev-parse HEAD)" || die "worker ${id} has no commit" 4
    git merge-base --is-ancestor "$base" "$tip" \
      || die "task ${id} no longer descends from the wave base" 4
    task_file="$(state_get "task_file.$id")"
    [[ -n "$task_file" && -f "$task_file" ]] \
      || die "task ${id} needs a task-file mapping; restart with --task ${id}=<task.md>" 5
    merge_head="$(git -C "$worker_path" rev-parse -q --verify MERGE_HEAD 2>/dev/null || true)"
    if [[ -n "$(git -C "$worker_path" status --porcelain)" && -z "$merge_head" ]]; then
      die "task ${id} has uncommitted changes" 5
    fi
    if [[ "$tip" != "$base" ]]; then
      commits="$(git -C "$worker_path" rev-list --reverse --first-parent "$base..$tip")" \
        || die "could not enumerate task ${id} commits" 5
      while IFS= read -r commit; do
        [[ -n "$commit" ]] || continue
        check_task_commit "$id" "$worker_path" "$task_file" "$commit"
      done <<<"$commits"
    fi
    printf 'checked_tip.%s=%s\n' "$id" "$tip" >> "$state"
  done

  # Sync each behind worker with the queue tip, then fast-forward the queue.
  for id in $tasks; do
    task_index=$((task_index + 1))
    (( task_index <= task_limit )) || break
    worker_path="$repo/.varde/worktrees/$id"
    tip="$(git -C "$worker_path" rev-parse HEAD)"
    [[ "$tip" == "$(state_get "checked_tip.$id")" ]] \
      || die "task ${id} changed after its ownership check" 4
    queue_tip="$(git -C "$iw" rev-parse HEAD)"
    position=$((position + 1))
    if [[ "$tip" == "$base" ]]; then
      printf 'tip.%s=%s\nqueue_tip.%s=%s\nqueue_position.%s=0\n' \
        "$id" "$tip" "$id" "$queue_tip" "$id" >> "$state"
      echo "skip $id (no commits)"
      position=$((position - 1))
      continue
    fi
    printf 'queue_position.%s=%s\n' "$id" "$position" >> "$state"

    merge_head="$(git -C "$worker_path" rev-parse -q --verify MERGE_HEAD 2>/dev/null || true)"
    if [[ -n "$merge_head" ]]; then
      paths="$(git -C "$worker_path" diff --name-only --diff-filter=U | paste -sd, -)"
      conflicts+=("conflict_in=${id} paths=${paths:-unknown}")
      printf 'queue_tip.%s=%s\n' "$id" "$queue_tip" >> "$state"
      break
    fi

    if git -C "$iw" merge-base --is-ancestor "$tip" "$queue_tip"; then
      printf 'tip.%s=%s\nqueue_tip.%s=%s\n' "$id" "$tip" "$id" "$queue_tip" >> "$state"
      if [[ "$tip" == "$queue_tip" ]]; then
        echo "skip $id (tip equals queue target)"
      else
        echo "skip $id (already integrated)"
      fi
      continue
    fi

    if ! git -C "$iw" merge-base --is-ancestor "$queue_tip" "$tip"; then
      rc=0
      output_dir="$(mktemp -d "$(dirname "$state")/.sync.XXXXXX")" \
        || die "could not capture worker sync output for ${id}" 5
      git -C "$worker_path" merge --no-ff --no-edit "$queue_tip" \
        >"$output_dir/stdout" 2>"$output_dir/stderr" || rc=$?
      if [[ "$rc" != 0 ]]; then
        merge_head="$(git -C "$worker_path" rev-parse -q --verify MERGE_HEAD 2>/dev/null || true)"
        if [[ -n "$merge_head" ]]; then
          paths="$(git -C "$worker_path" diff --name-only --diff-filter=U | paste -sd, -)"
          conflicts+=("conflict_in=${id} paths=${paths:-unknown}")
          printf 'queue_tip.%s=%s\n' "$id" "$queue_tip" >> "$state"
          rm -rf -- "$output_dir"
          break
        fi
        [[ ! -s "$output_dir/stdout" ]] || cat "$output_dir/stdout" >&2
        [[ ! -s "$output_dir/stderr" ]] || cat "$output_dir/stderr" >&2
        rm -rf -- "$output_dir"
        die "could not sync queue tip into task ${id} (exit ${rc})" 5
      fi
      rm -rf -- "$output_dir"
      tip="$(git -C "$worker_path" rev-parse HEAD)"
    fi

    if [[ "$tip" != "$queue_tip" ]]; then
      git -C "$iw" merge --ff-only "$tip" \
        || die "worker ${id} does not fast-forward the queue after sync" 4
      echo "merged worktree/${id} into worktree/${integration} at ${tip}"
    else
      echo "skip $id (tip equals queue target)"
    fi
    queue_tip="$(git -C "$iw" rev-parse HEAD)"
    printf 'tip.%s=%s\nqueue_tip.%s=%s\n' "$id" "$tip" "$id" "$queue_tip" >> "$state"
  done

  if [[ ${#conflicts[@]} -gt 0 ]]; then
    printf '%s\n' "${conflicts[@]}" >&2
    die "resolve the named worker conflicts and rerun integrate" 3
  fi
}

task_at_position() {
  local wanted="$1" id position=0
  for id in $tasks; do
    position=$((position + 1))
    if (( position == wanted )); then
      printf '%s' "$id"
      return 0
    fi
  done
  return 1
}

queue_tip_at_position() {
  local wanted="$1" id tip
  if (( wanted == 0 )); then
    printf '%s' "$base"
    return 0
  fi
  id="$(task_at_position "$wanted")" || return 1
  tip="$(state_get "queue_tip.$id")"
  [[ -n "$tip" ]] || return 1
  printf '%s' "$tip"
}

tasks_from_position() {
  local start="$1" end="$2" id position=0 result=""
  for id in $tasks; do
    position=$((position + 1))
    (( position >= start && position <= end )) || continue
    result="${result:+$result }$id"
  done
  printf '%s' "$result"
}

bisect_gate_failure() {
  local check="$1" task_count low=0 high mid prefix_tip verified_commit
  local culprit remainder after id worker_path current_tip expected_tip checked_tip position=0
  task_count="$(wc -w <<<"$tasks" | tr -d ' ')"
  high="$task_count"
  if (( task_count > 1 )); then
    while (( high - low > 1 )); do
      mid=$(((low + high) / 2))
      prefix_tip="$(queue_tip_at_position "$mid")" \
        || die "missing queue tip for task prefix ending at position ${mid}" 5
      git -C "$iw" reset --hard "$prefix_tip" >/dev/null \
        || die "could not probe task prefix ending at position ${mid}" 5
      if run_integrated_check "$check"; then
        low="$mid"
      else
        high="$mid"
      fi
    done
  fi

  if (( high == 1 )) && ! git -C "$iw" reset --hard "$base" >/dev/null; then
    die "could not probe the wave base" 5
  fi
  if (( high == 1 )) && ! run_integrated_check "$check"; then
    # Even the wave base fails the check; no task is responsible.
    printf 'culprit=base\n' >> "$state"
    echo "culprit=base"
    exit 5
  fi

  verified_commit="$(queue_tip_at_position "$low")" \
    || die "missing verified queue tip for task prefix ending at position ${low}" 5
  git -C "$iw" reset --hard "$verified_commit" >/dev/null \
    || die "could not restore the verified task prefix" 5
  for id in $tasks; do
    position=$((position + 1))
    worker_path="$repo/.varde/worktrees/$id"
    expected_tip="$(state_get "tip.$id")"
    current_tip="$(git -C "$worker_path" rev-parse HEAD)" \
      || die "could not inspect task ${id} after prefix bisection" 4
    [[ -n "$expected_tip" && "$current_tip" == "$expected_tip" ]] \
      || die "worker ${id} changed during prefix bisection" 4
    if (( position > high )); then
      # Keep later, unverified workers free of this batch's queue syncs.
      checked_tip="$(state_get "checked_tip.$id")"
      [[ -n "$checked_tip" ]] || die "missing pre-sync tip for task ${id}" 4
      git -C "$worker_path" reset --hard "$checked_tip" >/dev/null \
        || die "could not restore task ${id} to its pre-sync tip" 4
      printf 'tip.%s=%s\n' "$id" "$checked_tip" >> "$state"
    fi
  done
  after="$(verification_snapshot "$low")" \
    || die "integration or worker changed during prefix bisection" 4
  [[ "$(sed -n '1s/^integration=//p' <<<"$after")" == "$verified_commit" ]] \
    || die "integration changed during prefix bisection" 4
  for id in $tasks; do
    worker_path="$repo/.varde/worktrees/$id"
    expected_tip="$(state_get "tip.$id")"
    current_tip="$(git -C "$worker_path" rev-parse HEAD)" \
      || die "could not inspect task ${id} after prefix bisection" 4
    [[ -n "$expected_tip" && "$current_tip" == "$expected_tip" ]] \
      || die "worker ${id} changed during prefix bisection" 4
  done
  printf 'verified_task_count=%s\nverified_commit=%s\n' "$low" "$verified_commit" >> "$state"
  printf '%s' "$check" > "$state.check"
  printf '%s\n' "$after" > "$state.verified"
  culprit="$(task_at_position "$high")" || die "could not identify the failing task prefix" 5
  remainder="$(tasks_from_position "$high" "$task_count")"
  echo "culprit=$culprit"
  echo "verified_prefix=$verified_commit"
  echo "untouched_remainder=$remainder"
  exit 5
}

# Rebuild the verified integration on a moved plan branch, then rerun the
# stored combined check before the branch moves again.
rebuild_integration() {
  local target_tip="$1" check snapshot after task_limit paths
  git merge-base --is-ancestor "$base" "$target_tip" || die "plan branch moved outside the wave history; refs kept" 4
  [[ -f "$state.check" ]] || die "stored combined check is missing; rerun integrate" 4
  if git -C "$iw" rev-parse -q --verify MERGE_HEAD >/dev/null; then
    paths="$(git -C "$iw" diff --name-only --diff-filter=U | paste -sd, -)"
    echo "conflict_in=integration paths=${paths:-unknown}" >&2
    die "resolve the integration conflict and rerun integrate" 3
  fi
  [[ "$(git -C "$iw" symbolic-ref --quiet --short HEAD)" == "worktree/$integration" && -z "$(git -C "$iw" status --porcelain)" ]] || die "integration checkout is dirty or on another branch" 4

  task_limit="$(state_get verified_task_count)"
  [[ -n "$task_limit" ]] || task_limit="$(wc -w <<<"$tasks" | tr -d ' ')"
  rm -f "$state.verified"
  git -C "$iw" reset --hard "$target_tip" >/dev/null || die "could not rebuild integration on the moved plan branch; refs kept" 4
  printf 'target_base=%s\n' "$target_tip" >> "$state"
  merge_workers "$task_limit"
  snapshot="$(verification_snapshot "$task_limit")" || die "integration or worker changed before re-verification" 4
  check="$(cat "$state.check")" || die "could not read stored combined check" 4
  run_integrated_check "$check" || die "combined check failed after the plan branch moved; refs kept" 5
  after="$(verification_snapshot "$task_limit")" || die "check changed integration or workers; refs kept" 4
  [[ "$snapshot" == "$after" ]] || die "integration or worker tip changed during check; rerun integrate" 4
  printf 'verified_task_count=%s\nverified_commit=%s\n' \
    "$task_limit" "$(git -C "$iw" rev-parse HEAD)" >> "$state"
  printf '%s\n' "$snapshot" > "$state.verified"
  report_integration
}

# Fast-forward the plan branch to the verified integration commit.
commit_to_target() {
  local verified="$1" target_tip prior
  [[ -z "$(git status --porcelain)" ]] || die "plan worktree is dirty; refs kept" 4
  target_tip="$(git rev-parse HEAD)"
  if [[ "$target_tip" == "$verified" ]] || git merge-base --is-ancestor "$verified" "$target_tip"; then
    echo "plan branch already contains the verified integration commit"
    return 0
  fi
  prior="$(state_get integrated)"
  if [[ -n "$prior" && "$target_tip" == "$prior" ]]; then
    git merge --ff-only "$verified" || die "cannot fast-forward ${target}; refs kept" 4
  elif [[ "$target_tip" != "$target_base" ]]; then
    rebuild_integration "$target_tip"
    verified="$(git -C "$iw" rev-parse HEAD)"
    git merge --ff-only "$verified" || die "cannot fast-forward ${target}; refs kept" 4
  else
    git merge --ff-only "$verified" || die "cannot fast-forward ${target}; refs kept" 4
  fi
  [[ "$(state_get integrated)" == "$verified" ]] || echo "integrated=$verified" >> "$state"
  echo "fast-forwarded ${target} to ${verified}"
}

integrate() {
  [[ $# == 2 && "${1:-}" == "--check" && -n "${2:-}" ]] || { usage >&2; exit 1; }
  local check="$2" snapshot after task_count
  load_state
  require_plan_target
  [[ -n "$(state_get started)" ]] || die "wave ${wave} did not finish start; rerun start to resume"
  [[ -z "$(git status --porcelain)" ]] || die "plan worktree is dirty; commit or stash before integrating" 4
  if branch_exists "worktree/$integration"; then
    [[ -d "$iw" ]] || die "integration worktree ${iw} is missing; clean up and restart the wave" 4
  else
    "$HERE/worktree-create.sh" --fresh "$integration" "$base" >/dev/null
  fi

  if snapshot="$(verification_snapshot)" && [[ -f "$state.verified" && -f "$state.check" && "$(cat "$state.verified")" == "$snapshot" ]] && cmp -s "$state.check" <(printf '%s' "$check"); then
    echo "nothing to integrate; queue tip is already verified"
    commit_to_target "$(git -C "$iw" rev-parse HEAD)"
    report_integration
    return
  fi

  rm -f "$state.verified" "$state.check"
  if git -C "$iw" rev-parse -q --verify MERGE_HEAD >/dev/null; then
    paths="$(git -C "$iw" diff --name-only --diff-filter=U | paste -sd, -)"
    echo "conflict_in=integration paths=${paths:-unknown}" >&2
    die "resolve the integration conflict and rerun integrate" 3
  fi
  [[ "$(git -C "$iw" symbolic-ref --quiet --short HEAD)" == "worktree/$integration" && -z "$(git -C "$iw" status --porcelain)" ]] || die "integration checkout is dirty or on another branch" 4
  merge_workers
  snapshot="$(verification_snapshot)" || die "integration or worker changed before verification" 4
  acquire_integrate_lock
  if ! run_measured_check "$check"; then
    bisect_gate_failure "$check"
  fi
  after="$(verification_snapshot)" || die "check changed integration or workers; refs kept" 4
  [[ "$snapshot" == "$after" ]] || die "integration or worker tip changed during check; rerun integrate" 4
  task_count="$(wc -w <<<"$tasks" | tr -d ' ')"
  printf 'verified_task_count=%s\nverified_commit=%s\n' \
    "$task_count" "$(git -C "$iw" rev-parse HEAD)" >> "$state"
  printf '%s' "$check" > "$state.check"
  printf '%s\n' "$snapshot" > "$state.verified"
  commit_to_target "$(git -C "$iw" rev-parse HEAD)"
  report_integration
}

release() {
  [[ $# -eq 0 ]] || { usage >&2; exit 1; }
  local id pending=() pool="$repo/.varde/worktrees/pool" pool_max="${VARDE_WORKTREE_POOL_MAX:-4}"
  if [[ "$keep" == true ]]; then
    [[ "$pool_max" =~ ^[0-9]+$ ]] || die "VARDE_WORKTREE_POOL_MAX must be a non-negative integer"
    mkdir -p "$pool"
  fi
  load_state
  for id in $tasks "$integration"; do
    branch_exists "worktree/$id" || {
      echo "skip $id (already cleaned up)"
      continue
    }
    if [[ "$keep" == true && "$id" != "$integration" ]]; then
      local worker="$repo/.varde/worktrees/$id" dest="$pool/$id" branch="worktree/$id"
      if [[ ! -d "$worker" || -n "$(git -C "$worker" status --porcelain --untracked-files=all 2>/dev/null)" ]]; then
        pending+=("leave dirty worktree/$id in place")
      elif ! git merge-base --is-ancestor "$branch" HEAD; then
        pending+=("leave unmerged worktree/$id in place")
      else
        if [[ -e "$dest" ]]; then
          git worktree remove --force "$dest" || pending+=("remove old pooled worktree $dest")
        fi
        if ! varde setup watch --stop --remove-index --repo "$worker" >/dev/null 2>&1; then
          echo "warning: watcher stop or index removal failed for $worker" >&2
        fi
        if git -C "$worker" checkout --detach >/dev/null 2>&1 && git worktree move "$worker" "$dest" >&2; then
          git branch -d "$branch" >/dev/null || pending+=("delete branch $branch")
        else
          pending+=("pool clean worktree/$id")
        fi
      fi
    else
      "$HERE/worktree-cleanup.sh" "$id" || pending+=("clean up worktree/$id")
    fi
  done
  if [[ "$keep" == true ]]; then
    local count=0 candidate
    while IFS=$'\t' read -r _ candidate; do
      [[ -n "$candidate" ]] || continue
      count=$((count + 1))
      if (( count > pool_max )); then
        git worktree remove --force "$candidate" || pending+=("remove excess pooled worktree $candidate")
      fi
    done < <(find "$pool" -mindepth 1 -maxdepth 1 -type d -exec sh -c 'for p; do m=$(stat -c %Y "$p" 2>/dev/null || stat -f %m "$p"); printf "%s\t%s\n" "$m" "$p"; done' sh {} + | sort -n)
  fi
  report_pending "${pending[@]:-}"
  rm -f "$state" "$state.verified" "$state.check"
  echo "released and cleaned up wave ${wave}"
}

report_pending() {
  [[ -n "${1:-}" ]] || return 0
  echo "pending (refs kept; fix, then rerun: ${SELF} release ${wave}):" >&2
  printf '  - %s\n' "$@" >&2
  exit 1
}

case "$cmd" in
  start|integrate|release) "$cmd" "$@" ;;
  *) usage >&2; exit 1 ;;
esac
