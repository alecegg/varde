#!/usr/bin/env bash
# Regression test for worktree-wave.sh start|integrate|release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAVE="$SCRIPT_DIR/../varde-change/scripts/worktree-wave.sh"
TEST_ROOT="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/worktree-wave.XXXXXX")" && pwd -P)"
trap 'chmod -R u+w "$TEST_ROOT"; rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export VARDE_REAL_BIN="${VARDE_BIN:-$(command -v varde || true)}"

# Stub varde for the watcher and for ownership checks when no real binary is
# available; a real varde serves check-task-ownership so stray paths are caught.
mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/varde" <<STUB
#!/usr/bin/env bash
if [[ "\${1:-} \${2:-}" == "setup watch" ]]; then
  echo "cwd=\$PWD \$*" >> "$TEST_ROOT/calls.log"
  exit 0
fi
if [[ "\${1:-}" == plan && "\${2:-}" == check-task-ownership ]]; then
  echo "cwd=\$PWD \$*" >> "$TEST_ROOT/calls.log"
  if [[ -n "\${VARDE_REAL_BIN:-}" ]]; then
    exec "\$VARDE_REAL_BIN" "\$@"
  fi
  echo '{"data":{"status":"ok","stray":[],"declared":[],"changed":[]}}'
  exit 0
fi
echo "unexpected varde invocation: \$*" >&2
exit 2
STUB
chmod +x "$TEST_ROOT/bin/varde"
export PATH="$TEST_ROOT/bin:$PATH"

repo="$TEST_ROOT/repo"
git init -q -b main "$repo"
echo base > "$repo/shared.txt"
mkdir -p "$repo/clis"
printf '[workspace]\n' > "$repo/clis/Cargo.toml"
git -C "$repo" add shared.txt clis/Cargo.toml
git -C "$repo" commit -q -m base
echo '*.ignored' >> "$repo/.git/info/exclude"

# The wave targets the plan branch checked out in the plan worktree.
plan="$repo/.varde/worktrees/plan"
git -C "$repo" worktree add -q -b worktree/plan "$plan" main
cd "$plan"

run() {
  local want="$1" got=0; shift
  "$WAVE" "$@" >"$TEST_ROOT/stdout" 2>"$TEST_ROOT/stderr" || got=$?
  out="$(cat "$TEST_ROOT/stdout" "$TEST_ROOT/stderr")"
  [[ "$got" == "$want" ]] || fail "wave $*: expected exit $want, got $got: $out"
}
wt() { echo "$repo/.varde/worktrees/$1"; }
write_task() { # <file> <modifies...>
  local file="$1"; shift
  mkdir -p "$(dirname "$file")"
  {
    printf -- '---\nstatus: in_progress\ntype: task\n'
    if [[ $# -gt 0 ]]; then
      printf 'modifies:\n'
      printf '  - %s\n' "$@"
    else
      printf 'modifies: []\n'
    fi
    printf -- '---\n'
  } >"$file"
}
commit_in() { # <task> <file> <content>
  echo "$3" > "$(wt "$1")/$2"
  git -C "$(wt "$1")" add "$2"
  git -C "$(wt "$1")" commit -q -m "$1"
}
branch_exists() { git show-ref --verify --quiet "refs/heads/$1"; }
force_clean() {
  git worktree remove --force "$(wt "$1")" 2>/dev/null || true
  git branch -D "worktree/$1" >/dev/null 2>&1 || true
}
has() { grep -q -- "$2" <<<"$1" || fail "$3: missing '$2' in: $1"; }
has_fixed() { grep -Fq -- "$2" <<<"$1" || fail "$3: missing '$2' in: $1"; }

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

# --- Wave w1: start, ownership checks, queue, one batch check, release -------
base1="$(git rev-parse HEAD)"
task_ta="$TEST_ROOT/tasks/ta.md"; write_task "$task_ta" a.txt
task_tb="$TEST_ROOT/tasks/tb.md"; write_task "$task_tb" b.txt
run 0 start w1 ta tb --task "ta=$task_ta" --task "tb=$task_tb"
[[ -d "$(wt ta)" && -d "$(wt tb)" ]] || fail "start did not create worker worktrees"
[[ "$(git -C "$(wt ta)" rev-parse HEAD)" == "$base1" ]] || fail "worker not at recorded base"
[[ "$(sed -n 's/^status: //p' "$task_ta")" == in_progress ]] || fail "task status changed"
has "$out" "task=ta" "start context"; has "$out" "branch=worktree/tb" "start context"
grep -qx "task_file.ta=$task_ta" "$state_dir/w1" || fail "task file not recorded"

commit_in ta a.txt a
commit_in tb b.txt b
check1="test -f a.txt && test -f b.txt && echo checked >> '$TEST_ROOT/check-count'"
run 0 integrate w1 --check "$check1"
[[ -f a.txt && -f b.txt ]] || fail "plan branch lacks merged files"
has "$out" "verified_commit=" "integrate report"
[[ "$(wc -l < "$TEST_ROOT/check-count" | tr -d ' ')" == 1 ]] || fail "batch check did not run once"
grep -c 'plan check-task-ownership' "$TEST_ROOT/calls.log" >/dev/null || fail "ownership checks were not run"
# An immovable verified result is reused; the plan branch already contains it.
verified1="$(git -C "$(wt w1-integration)" rev-parse HEAD)"
run 0 integrate w1 --check "$check1"
[[ "$(wc -l < "$TEST_ROOT/check-count" | tr -d ' ')" == 1 ]] || fail "unchanged successful check ran again"
has "$out" "nothing to integrate" "idempotent integrate"
[[ "$(git rev-parse HEAD)" == "$verified1" ]] || fail "idempotent integrate moved the plan branch"

run 0 release w1
for b in ta tb w1-integration; do
  branch_exists "worktree/$b" && fail "worktree/$b not cleaned up"
  [[ -d "$(wt "$b")" ]] && fail "worktree path $b not cleaned up"
done

# An executable branch binary suppresses the installed-varde warning.
mkdir -p "$plan/clis/target/debug"
printf '/clis/target/\n' >> "$repo/.git/info/exclude"
cat > "$plan/clis/target/debug/varde" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$plan/clis/target/debug/varde"
git -C "$plan" add -f clis/target/debug/varde
git -C "$plan" commit -q -m 'add built branch varde fixture'
task_bin="$TEST_ROOT/tasks/bin.md"; write_task "$task_bin" bin.txt
run 0 start wb bin --task "bin=$task_bin"
commit_in bin bin.txt built
run 5 integrate wb --check "test -f bin.txt && false"
! grep -q 'warning: clis/target/debug/varde is missing' <<<"$out" || fail "built branch varde still warned"
commit_in bin bin.txt fixed
run 0 integrate wb --check 'test -f bin.txt'
run 0 release wb
rm -rf "$plan/clis/target"
git -C "$plan" add -u clis/target/debug/varde
git -C "$plan" commit -q -m 'remove built branch varde fixture'

# --- Wave w2: ownership rejection before the queue --------------------------
base2="$(git rev-parse HEAD)"
task_to="$TEST_ROOT/tasks/to.md"; write_task "$task_to" owned.txt
task_ts="$TEST_ROOT/tasks/ts.md"; write_task "$task_ts" shared.txt
run 0 start w2 to ts --task "to=$task_to" --task "ts=$task_ts"
commit_in to owned.txt in-scope
commit_in ts stray.txt out-of-scope
run 5 integrate w2 --check true
has_fixed "$out" '"code":"ownership_stray"' "ownership rejection error code"
has_fixed "$out" '"stray":["stray.txt"]' "ownership rejection exact stray path"
[[ "$(git rev-parse HEAD)" == "$base2" ]] || fail "ownership rejection moved the plan branch"
for id in to ts w2-integration; do force_clean "$id"; done
rm -f "$state_dir/w2"

# --- Wave w3: conflict in the worker, then resolve ---------------------------
base3="$(git rev-parse HEAD)"
task_tc="$TEST_ROOT/tasks/tc.md"; write_task "$task_tc" shared.txt
task_td="$TEST_ROOT/tasks/td.md"; write_task "$task_td" shared.txt
run 0 start w3 tc td --task "tc=$task_tc" --task "td=$task_td"
commit_in tc shared.txt c
commit_in td shared.txt d
run 3 integrate w3 --check true
has "$out" "conflict_in=td" "worker conflict report"
has "$out" "shared.txt" "worker conflict paths"
[[ "$(git rev-parse HEAD)" == "$base3" ]] || fail "conflict moved the plan branch"
echo resolved > "$(wt td)/shared.txt"
git -C "$(wt td)" add shared.txt
git -C "$(wt td)" commit -q --no-edit
run 0 integrate w3 --check 'test "$(cat shared.txt)" = resolved'
[[ "$(cat shared.txt)" == resolved ]] || fail "resolved merge did not reach the plan branch"
run 0 release w3

# --- Wave w4: a failing batch bisects to the culprit -------------------------
base4="$(git rev-parse HEAD)"
task_ba="$TEST_ROOT/tasks/ba.md"; write_task "$task_ba" ba.txt
task_bb="$TEST_ROOT/tasks/bb.md"; write_task "$task_bb" bb.txt
task_bc="$TEST_ROOT/tasks/bc.md"; write_task "$task_bc" bc.txt
task_bd="$TEST_ROOT/tasks/bd.md"; write_task "$task_bd" bd.txt
run 0 start w4 ba bb bc bd --task "ba=$task_ba" --task "bb=$task_bb" --task "bc=$task_bc" --task "bd=$task_bd"
commit_in ba ba.txt a
commit_in bb bb.txt b
commit_in bc bc.txt c
commit_in bd bd.txt d
bisect_check="echo gate >> '$TEST_ROOT/bisect-count'; test -f ba.txt && test -f bb.txt && test ! -f bc.txt"
run 5 integrate w4 --check "$bisect_check"
has "$out" "warning: clis/target/debug/varde is missing; integrated check will use the installed varde" "missing branch varde warning"
has "$out" "culprit=bc" "bisect culprit"
has "$out" "untouched_remainder=bc bd" "bisect untouched remainder"
[[ "$(git rev-parse HEAD)" == "$base4" ]] || fail "failed batch moved the plan branch"
bisect_tip="$(git rev-parse worktree/bb)"
has "$out" "verified_prefix=$bisect_tip" "exact bisect verified prefix"
[[ "$(git rev-parse worktree/w4-integration)" == "$bisect_tip" ]] || fail "bisection did not leave integration at the passing prefix"
[[ "$(grep -c '^gate$' "$TEST_ROOT/bisect-count")" == 3 ]] || fail "four-task bisection did not use one batch gate and two probes"
commit_in bc bc.txt fixed
run 0 integrate w4 --check 'test -f ba.txt && test -f bb.txt && test -f bc.txt && test -f bd.txt'
[[ "$(git rev-parse HEAD)" == "$(git rev-parse worktree/w4-integration)" ]] || fail "fixed batch did not fast-forward the plan branch"
run 0 release w4

# --- Wave w5: a single-task failure runs one batch gate plus a base probe ---
base5="$(git rev-parse HEAD)"
task_sf="$TEST_ROOT/tasks/sf.md"; write_task "$task_sf" sf.txt
run 0 start w5 sf --task "sf=$task_sf"
commit_in sf sf.txt fail
# The check passes at the base and fails once the task commit lands.
run 5 integrate w5 --check "echo gate >> '$TEST_ROOT/single-count'; test ! -f sf.txt"
has "$out" "culprit=sf" "single-task failure culprit"
[[ "$(grep -c '^gate$' "$TEST_ROOT/single-count")" == 2 ]] || fail "single-task failure did not probe the passing base"
[[ "$(git rev-parse HEAD)" == "$base5" ]] || fail "single-task failure moved the plan branch"
commit_in sf sf.txt fixed
run 0 integrate w5 --check 'test -f sf.txt'
run 0 release w5

# --- Wave w5b: a base that already fails the check blames the base -------------
base5b="$(git rev-parse HEAD)"
task_sfb="$TEST_ROOT/tasks/sfb.md"; write_task "$task_sfb" sfb.txt
run 0 start w5b sfb --task "sfb=$task_sfb"
commit_in sfb sfb.txt fail
run 5 integrate w5b --check "echo gate >> '$TEST_ROOT/base-fail-count'; false"
has "$out" "culprit=base" "base-failure culprit"
! grep -q '^verified_prefix=' "$TEST_ROOT/stdout" || fail "base failure printed a verified prefix"
[[ "$(git rev-parse HEAD)" == "$base5b" ]] || fail "base-failure batch moved the plan branch"
[[ "$(grep -c '^gate$' "$TEST_ROOT/base-fail-count")" == 2 ]] || fail "base failure did not run the batch gate and one base probe"

# --- release removes the worktree with ignored files -------------------------
task_di="$TEST_ROOT/tasks/di.md"; write_task "$task_di" di.txt
run 0 start w6 di --task "di=$task_di"
commit_in di di.txt committed
run 0 integrate w6 --check 'test -f di.txt'
echo generated > "$(wt di)/generated.ignored"
run 0 release w6
! branch_exists worktree/di && [[ ! -d "$(wt di)" ]] || fail "release did not remove the worktree with ignored files"

# --- Legacy wave state is rejected with a restart command ---------------------
run 0 start legacy ta --task "ta=$task_ta"
state="$(git rev-parse --git-common-dir)/varde-waves/legacy"
python3 - "$state" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text('\n'.join(line for line in path.read_text().splitlines() if not line.startswith('queue_version=')) + '\n')
PY
run 4 integrate legacy --check true
has "$out" "restart with: worktree-wave.sh start <new-wave-id>" "legacy queue recovery"

# A skills-only checkout has no clis manifest and needs no warning.
git rm -q clis/Cargo.toml
git commit -q -m 'remove clis fixture'
task_noclis="$TEST_ROOT/tasks/noclis.md"; write_task "$task_noclis" noclis.txt
run 0 start w-no-clis noclis --task "noclis=$task_noclis"
commit_in noclis noclis.txt skills-only
run 5 integrate w-no-clis --check false
! grep -q 'warning: clis/target/debug/varde is missing' <<<"$out" || fail "skills-only wave warned about branch varde"
commit_in noclis noclis.txt fixed
run 0 integrate w-no-clis --check 'test -f noclis.txt'
run 0 release w-no-clis

echo "PASS: worktree-wave"
