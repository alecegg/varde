#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAVE="$SCRIPT_DIR/../varde-change/scripts/worktree-wave.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/wave-reuse.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

repo="$TEST_ROOT/repo"
mkdir -p "$repo"
git -C "$repo" init -q
git -C "$repo" config user.email test@example.invalid
git -C "$repo" config user.name Test
echo marker > "$repo/.gitignore"
printf 'build/\n' > "$repo/.gitignore"
echo task > "$TEST_ROOT/task.md"
git -C "$repo" add .gitignore
git -C "$repo" commit -qm base
branch="$(git -C "$repo" branch --show-current)"

start() {
  local wave="$1" task="$2"
  (cd "$repo" && VARDE_WORKTREE_POOL_MAX=2 "$WAVE" start "$wave" "$task" --task "$task=$TEST_ROOT/task.md" >/dev/null)
}
release() { (cd "$repo" && VARDE_WORKTREE_POOL_MAX=2 "$WAVE" release "$1" "${@:2}"); }
worker="$repo/.varde/worktrees/reuse-a"
start reuse-one reuse-a
mkdir -p "$worker/build"
echo warm > "$worker/build/marker"
release reuse-one --keep || fail 'release --keep failed'
[[ -f "$repo/.varde/worktrees/pool/reuse-a/build/marker" ]] || fail 'clean worktree was not moved into pool'

# Record git worktree-add calls; the next start must move the pooled checkout.
mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/git" <<'GIT'
#!/usr/bin/env bash
if [[ "$*" == *"worktree add"* ]]; then echo "$*" >> "$GIT_ADD_LOG"; fi
exec /usr/bin/git "$@"
GIT
chmod +x "$TEST_ROOT/bin/git"
export GIT_ADD_LOG="$TEST_ROOT/worktree-add.log" PATH="$TEST_ROOT/bin:$PATH"
start reuse-two reuse-b
new_worker="$repo/.varde/worktrees/reuse-b"
[[ -f "$new_worker/build/marker" ]] || fail 'pooled ignored marker did not survive reuse'
[[ ! -s "$GIT_ADD_LOG" ]] || fail 'pooled worker was recreated with git worktree add'
release reuse-two --keep || fail 'second release --keep failed'

# Dirty task worktrees must remain and be reported, not discarded.
start dirty-wave dirty-task
echo dirty > "$repo/.varde/worktrees/dirty-task/tracked-dirty"
set +e
dirty_output="$(release dirty-wave --keep 2>&1)"
dirty_status=$?
set -e
[[ "$dirty_status" == 1 && "$dirty_output" == *'leave dirty worktree/dirty-task in place'* ]] || fail 'dirty worktree was not reported pending'
[[ -e "$repo/.varde/worktrees/dirty-task" ]] || fail 'dirty worktree was removed'
[[ ! -e "$repo/.varde/worktrees/pool/dirty-task" ]] || fail 'dirty worktree entered the pool'

# A pool cap of one keeps only one of two clean workers.
(cd "$repo" && VARDE_WORKTREE_POOL_MAX=1 "$WAVE" start cap-wave cap-a cap-b --task "cap-a=$TEST_ROOT/task.md" --task "cap-b=$TEST_ROOT/task.md" >/dev/null)
(cd "$repo" && VARDE_WORKTREE_POOL_MAX=1 "$WAVE" release cap-wave --keep) || fail 'capped release failed'
[[ "$(find "$repo/.varde/worktrees/pool" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" -le 1 ]] || fail 'pool cap was exceeded'

if release reuse-two --bogus >/dev/null 2>&1; then fail 'unknown release flag was accepted'; fi

echo 'PASS: wave-worktree-reuse'
