#!/usr/bin/env bash
# Fast regression cases for worktree-wave.sh start|integrate|release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/wave-fixture.sh"

help="$($WAVE --help)"
has "$help" "start <wave-id> <task-id>..." "start usage"
has "$help" "integrate <wave-id> --check" "integrate usage"
has "$help" "release <wave-id>" "release usage"
has "$help" "culprit=<task>" "integrate failure help"
has "$help" "verified_prefix=<commit>" "verified prefix help"
has "$help" "untouched_remainder=<tasks>" "untouched remainder help"
! grep -q 'publish' <<<"$help" || fail "removed publish step remains in help"
has "$help" "integration-check lock before timeout" "lock wait exit code help"

# A missing task-file mapping is refused before creating wave state or workers.
state_dir="$(git rev-parse --git-common-dir)/varde-waves"
run 1 start no-map missing-task
[[ ! -e "$state_dir/no-map" && ! -d "$(wt missing-task)" ]] || fail "missing task mapping mutated the wave"

# --- Wave plan-w1: start, ownership checks, queue, one batch check, release -------
base1="$(git rev-parse HEAD)"
task_ta="$TEST_ROOT/tasks/ta.md"; write_task "$task_ta" a.txt

# Start is limited to plan worktrees under the repository worktree directory.
outside_plan="$TEST_ROOT/outside-plan"
git -C "$repo" worktree add -q -b worktree/outside-plan "$outside_plan" main
python3 - "$outside_plan" "$WAVE" "$task_ta" "$repo" <<'PYTEST'
import subprocess
import sys
from pathlib import Path

plan, wave, task, repo = sys.argv[1:]
result = subprocess.run(
    [wave, "start", "outside-wave", "ta", "--task", f"ta={task}"],
    cwd=plan,
    capture_output=True,
    text=True,
)
assert result.returncode == 4, result.stdout + result.stderr
assert f"plan worktree must be under {repo}/.varde/worktrees" in (
    result.stdout + result.stderr
)
assert not (Path(repo) / ".git/varde-waves/outside-wave").exists()
PYTEST
# An unprefixed wave id is refused before it can collide with another plan's wave.
run 1 start w1 ta --task "ta=$task_ta"
has "$out" "must start with the plan id 'plan-'" "wave id plan prefix"
[[ ! -e "$state_dir/w1" && ! -d "$(wt ta)" ]] || fail "unprefixed wave id created state or workers"

task_tb="$TEST_ROOT/tasks/tb.md"; write_task "$task_tb" b.txt
run 0 start plan-w1 ta tb --task "ta=$task_ta" --task "tb=$task_tb"
[[ -d "$(wt ta)" && -d "$(wt tb)" ]] || fail "start did not create worker worktrees"
[[ "$(git -C "$(wt ta)" rev-parse HEAD)" == "$base1" ]] || fail "worker not at recorded base"
[[ "$(sed -n 's/^status: //p' "$task_ta")" == in_progress ]] || fail "task status changed"
has "$out" "task=ta" "start context"; has "$out" "branch=worktree/tb" "start context"
grep -qx "task_file.ta=$task_ta" "$state_dir/plan-w1" || fail "task file not recorded"

commit_in ta a.txt a
commit_in tb b.txt b
check1="test -f a.txt && test -f b.txt && echo checked >> '$TEST_ROOT/check-count'"
run 0 integrate plan-w1 --check "$check1"
[[ -f a.txt && -f b.txt ]] || fail "plan branch lacks merged files"
has "$out" "verified_commit=" "integrate report"
[[ "$(wc -l < "$TEST_ROOT/check-count" | tr -d ' ')" == 1 ]] || fail "batch check did not run once"
grep -c 'plan check-task-ownership' "$TEST_ROOT/calls.log" >/dev/null || fail "ownership checks were not run"
# An immovable verified result is reused; the plan branch already contains it.
verified1="$(git -C "$(wt plan-w1-integration)" rev-parse HEAD)"
run 0 integrate plan-w1 --check "$check1"
[[ "$(wc -l < "$TEST_ROOT/check-count" | tr -d ' ')" == 1 ]] || fail "unchanged successful check ran again"
has "$out" "nothing to integrate" "idempotent integrate"
[[ "$(git rev-parse HEAD)" == "$verified1" ]] || fail "idempotent integrate moved the plan branch"

STUB_WATCH_MODE=nolock run 0 release plan-w1
! grep -Fq "no watcher lock found for this repo set" <<<"$out" || fail "release warned about an absent watcher lock"
! grep -Fq "warning: watcher stop or index removal failed" <<<"$out" || fail "release warned after an absent watcher lock"
for b in ta tb plan-w1-integration; do
  branch_exists "worktree/$b" && fail "worktree/$b not cleaned up"
  [[ -d "$(wt "$b")" ]] && fail "worktree path $b not cleaned up"
done

# --- Wave plan-w2: ownership rejection before the queue --------------------------
base2="$(git rev-parse HEAD)"
task_to="$TEST_ROOT/tasks/to.md"; write_task "$task_to" owned.txt
task_ts="$TEST_ROOT/tasks/ts.md"; write_task "$task_ts" shared.txt
run 0 start plan-w2 to ts --task "to=$task_to" --task "ts=$task_ts"
commit_in to owned.txt in-scope
commit_in ts stray.txt out-of-scope
run 5 integrate plan-w2 --check true
has_fixed "$out" '"code":"ownership_stray"' "ownership rejection error code"
has_fixed "$out" '"stray":["stray.txt"]' "ownership rejection exact stray path"
[[ "$(git rev-parse HEAD)" == "$base2" ]] || fail "ownership rejection moved the plan branch"
for id in to ts plan-w2-integration; do force_clean "$id"; done
rm -f "$state_dir/plan-w2"

# --- Wave plan-w3: conflict in the worker, then resolve ---------------------------
base3="$(git rev-parse HEAD)"
task_tc="$TEST_ROOT/tasks/tc.md"; write_task "$task_tc" shared.txt
task_td="$TEST_ROOT/tasks/td.md"; write_task "$task_td" shared.txt
run 0 start plan-w3 tc td --task "tc=$task_tc" --task "td=$task_td"
commit_in tc shared.txt c
commit_in td shared.txt d
run 3 integrate plan-w3 --check true
has "$out" "conflict_in=td" "worker conflict report"
has "$out" "shared.txt" "worker conflict paths"
[[ "$(git rev-parse HEAD)" == "$base3" ]] || fail "conflict moved the plan branch"
echo resolved > "$(wt td)/shared.txt"
git -C "$(wt td)" add shared.txt
git -C "$(wt td)" commit -q --no-edit
run 0 integrate plan-w3 --check 'test "$(cat shared.txt)" = resolved'
[[ "$(cat shared.txt)" == resolved ]] || fail "resolved merge did not reach the plan branch"
STUB_WATCH_MODE=fail run 0 release plan-w3
has_fixed "$out" "warning: watcher stop or index removal failed" "real watcher stop failure warns"
has_fixed "$out" "watcher exploded" "real watcher stop failure shows output"

# --- Wave plan-w4: absent watcher lock plus an index error still warns --------------
run 0 start plan-w4 ta --task "ta=$task_ta"
STUB_WATCH_MODE=nolockindex run 0 release plan-w4
has_fixed "$out" "warning: watcher stop or index removal failed" "index error after absent lock warns"

# --- Legacy wave state is rejected with a restart command ---------------------
run 0 start plan-legacy ta --task "ta=$task_ta"
state="$(git rev-parse --git-common-dir)/varde-waves/plan-legacy"
python3 - "$state" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text('\n'.join(line for line in path.read_text().splitlines() if not line.startswith('queue_version=')) + '\n')
PY
run 4 integrate plan-legacy --check true
has "$out" "restart with: worktree-wave.sh start <new-wave-id>" "plan-legacy queue recovery"

echo "PASS: worktree-wave"
