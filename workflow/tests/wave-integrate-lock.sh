#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../core/tests/lib/repo.sh"
WAVE="$(skill_dir varde-orchestrate)/scripts/worktree-wave.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/wave-lock.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export VARDE_WRITE_LEDGER="$TEST_ROOT/writes.jsonl"
mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/varde" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-} ${2:-}" == "plan check-task-ownership" ]]; then
  echo '{"data":{"status":"ok","stray":[],"declared":[],"changed":[]}}'
  exit 0
fi
echo "unexpected varde invocation: $*" >&2
exit 2
STUB
chmod +x "$TEST_ROOT/bin/varde"
export PATH="$TEST_ROOT/bin:$PATH"

repo="$TEST_ROOT/repo"
git init -q -b main "$repo"
echo base > "$repo/base.txt"
git -C "$repo" add base.txt
git -C "$repo" commit -q -m base
echo 'measured.bin' >> "$repo/.git/info/exclude"

write_task() {
  printf '%s\n' '---' 'type: task' 'status: todo' 'modifies: []' '---' > "$TEST_ROOT/$1.md"
}
wave_id() { printf 'plan-%s-w1' "$1"; }
setup_wave() {
  local id="$1" task="$2" wave="$(wave_id "$1")" plan="$repo/.varde/worktrees/plan-$1"
  git -C "$repo" worktree add -q -b "worktree/plan-$id" "$plan" main
  git -C "$plan" config user.name t
  git -C "$plan" config user.email t@t
  (cd "$plan" && "$WAVE" start "$wave" "$task" --task "$task=$TEST_ROOT/$task.md" >/dev/null)
  echo "$id change" > "$repo/.varde/worktrees/$task/$task.txt"
  git -C "$repo/.varde/worktrees/$task" add "$task.txt"
  git -C "$repo/.varde/worktrees/$task" commit -q -m "$task"
}
run_wave() { (cd "$repo/.varde/worktrees/plan-$1" && "$WAVE" integrate "$(wave_id "$1")" --check "$2"); }

write_task a; write_task b
setup_wave alpha a
setup_wave beta b
common="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)"
log="$TEST_ROOT/intervals"
probe="$TEST_ROOT/checks"
mkdir -p "$probe"
# Each integration check holds the repository lock, so it publishes a live
# marker and polls for the other wave's marker instead of sleeping a fixed 2 s:
# a lock regression is seen in the first 50 ms poll, and the recorded intervals
# must not overlap either.
cat > "$TEST_ROOT/check.sh" <<'EOS'
#!/usr/bin/env bash
set -eu
id="$1"; other="$2"; log="$3"; probe="$4"
: > "$probe/$id.live"
printf 'start %s\n' "$(python3 -c 'import time; print(time.time())')" >> "$log"
for _ in $(seq 1 20); do
  if [ -e "$probe/$other.live" ]; then
    echo "$id check ran while $other was checking" >&2
    exit 1
  fi
  sleep 0.05
done
dd if=/dev/zero of=measured.bin bs=1024 count=2 2>/dev/null
printf 'end %s\n' "$(python3 -c 'import time; print(time.time())')" >> "$log"
rm -f "$probe/$id.live"
EOS
run_check() {
  local id="$1" other="$2"
  (cd "$repo/.varde/worktrees/plan-$id" && "$WAVE" integrate "$(wave_id "$id")" --check \
    "bash '$TEST_ROOT/check.sh' $id $other '$log' '$probe'")
}
run_check alpha beta >"$TEST_ROOT/alpha.out" 2>&1 & first=$!
run_check beta alpha >"$TEST_ROOT/beta.out" 2>&1 & second=$!
wait "$first" || fail "alpha integrate failed: $(cat "$TEST_ROOT/alpha.out")"
wait "$second" || fail "beta integrate failed: $(cat "$TEST_ROOT/beta.out")"
python3 - "$log" <<'PY' || fail 'combined integration checks overlapped'
import sys
rows = [line.split() for line in open(sys.argv[1])]
events = sorted((float(ts), kind) for kind, ts in rows)
active = 0
for _, kind in events:
    active += 1 if kind == "start" else -1
    if active > 1 or active < 0:
        raise SystemExit(1)
if active:
    raise SystemExit(1)
PY
for id in alpha beta; do
  grep -Eq '^check_write_bytes=[0-9]+$' "$common/varde-waves/$(wave_id "$id")" || fail "$id did not record check_write_bytes"
done

# A lock directory owned by a dead process is reclaimed.
write_task c; setup_wave gamma c
mkdir -p "$common/varde-waves/integrate.lock"
echo 99999999 > "$common/varde-waves/integrate.lock/pid"
run_wave gamma true >"$TEST_ROOT/dead.out" 2>&1 || fail "dead-pid lock was not reclaimed: $(cat "$TEST_ROOT/dead.out")"
[[ ! -e "$common/varde-waves/integrate.lock" ]] || fail 'lock remained after successful check'

# A pid-less lock older than the recovery grace period (3 s in worktree-wave.sh)
# is reclaimed. Backdate the lock instead of sleeping past the grace.
write_task c2; setup_wave epsilon c2
mkdir -p "$common/varde-waves/integrate.lock"
touch -t 200001010000 "$common/varde-waves/integrate.lock"
run_wave epsilon true >"$TEST_ROOT/pidless.out" 2>&1 || fail "pid-less lock was not reclaimed: $(cat "$TEST_ROOT/pidless.out")"

# A live holder is respected and the configured wait cap exits 6.
write_task d; setup_wave delta d
mkdir -p "$common/varde-waves/integrate.lock"
echo "$$" > "$common/varde-waves/integrate.lock/pid"
set +e
VARDE_INTEGRATE_LOCK_WAIT=1 run_wave delta true >"$TEST_ROOT/timeout.out" 2>&1
status=$?
set -e
[[ "$status" == 6 ]] || fail "held lock exited $status instead of 6"
rm -rf "$common/varde-waves/integrate.lock"

# Failing checks preserve culprit output and still release the lock.
set +e
run_wave delta 'echo check-output; test ! -f d.txt' >"$TEST_ROOT/fail.out" 2>&1
status=$?
set -e
[[ "$status" == 5 ]] || fail "failing check exited $status instead of 5"
grep -q 'culprit=d' "$TEST_ROOT/fail.out" || fail 'failing check did not report culprit'
grep -q 'check-output' "$TEST_ROOT/fail.out" || fail 'failing check output was lost'
grep -Eq '^check_write_bytes=[0-9]+$' "$common/varde-waves/$(wave_id delta)" || fail 'failed check bytes were not recorded'
[[ ! -e "$common/varde-waves/integrate.lock" ]] || fail 'lock remained after failing check'

echo 'PASS: wave-integrate-lock'
