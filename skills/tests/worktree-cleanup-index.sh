#!/usr/bin/env bash
# Regression test for worktree cleanup's watcher and index removal step.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP="$SCRIPT_DIR/../varde-change/scripts/worktree-cleanup.sh"
TEST_ROOT="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/worktree-cleanup-index.XXXXXX")" && pwd -P)"
trap 'chmod -R u+w "$TEST_ROOT"; rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
has() { grep -Fq -- "$2" <<<"$1" || fail "$3: missing '$2' in: $1"; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export WATCH_CALLS="$TEST_ROOT/watch-calls.log"
export WATCH_FAILURE=""

mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/varde" <<'STUB'
#!/usr/bin/env bash
[[ "$*" == "setup watch --stop --remove-index --repo "* ]] || {
  echo "unexpected varde invocation: $*" >&2
  exit 2
}
echo "$*" >> "$WATCH_CALLS"
case "${WATCH_FAILURE:-}" in
  stop) echo "simulated watcher stop failure"; exit 1 ;;
  remove) echo "simulated index removal failure"; exit 1 ;;
esac
exit 0
STUB
chmod +x "$TEST_ROOT/bin/varde"
export PATH="$TEST_ROOT/bin:$PATH"

repo="$TEST_ROOT/repo"
git init -q -b main "$repo"
cd "$repo"
printf '*.ignored\nbuild/\ntarget/\n.claude/.cc-writes/\n' > .gitignore
echo tracked > tracked.txt
git add .gitignore tracked.txt
git commit -q -m base

wt() { echo "$repo/.varde/worktrees/$1"; }
make_worker() {
  local id="$1" worktree
  worktree="$(wt "$id")"
  mkdir -p "$(dirname "$worktree")"
  git worktree add -q -b "worktree/$id" "$worktree" main
  echo "$id" > "$worktree/$id-extra.txt"
  git -C "$worktree" add "$id-extra.txt"
  git -C "$worktree" commit -q -m "$id"
  git merge --ff-only -q "worktree/$id"
}
run() {
  local want="$1" got=0
  shift
  "$CLEANUP" "$@" >"$TEST_ROOT/stdout" 2>"$TEST_ROOT/stderr" || got=$?
  out="$(cat "$TEST_ROOT/stdout" "$TEST_ROOT/stderr")"
  [[ "$got" == "$want" ]] || fail "cleanup $*: expected exit $want, got $got: $out"
}

# ignored_any_name: ignored output of any name (build dirs, .claude/.cc-writes)
# is listed and removed by plain cleanup with no extra flag.
make_worker ignored-any
mkdir -p "$(wt ignored-any)/build" "$(wt ignored-any)/target" "$(wt ignored-any)/.claude/.cc-writes"
echo built > "$(wt ignored-any)/build/out"
echo built > "$(wt ignored-any)/target/out"
echo activity > "$(wt ignored-any)/.claude/.cc-writes/log"
run 0 ignored-any
has "$out" "removing ignored files:" "ignored entries listed"
has "$out" "build/" "build output listed"
has "$out" "target/" "target output listed"
has "$out" ".claude/.cc-writes/" "claude cc-writes listed"
[[ ! -e "$(wt ignored-any)" ]] || fail "ignored_any_name: left the worktree"
echo "ok: ignored_any_name"

# Cleanup lists generated files and invokes the shared CLI.
make_worker clean
echo generated > "$(wt clean)/build.ignored"
WATCH_FAILURE=""
run 0 clean
[[ ! -e "$(wt clean)" ]] || fail "ignored-only cleanup left the worktree"
grep -F "setup watch --stop --remove-index --repo $(wt clean)" "$WATCH_CALLS" >/dev/null \
  || fail "cleanup did not stop the watcher and remove its index"

# Stop and index-removal failures warn, then cleanup still finishes.
for failure in stop remove; do
  id="warn-$failure"
  make_worker "$id"
  echo generated > "$(wt "$id")/build.ignored"
  export WATCH_FAILURE="$failure"
  run 0 "$id"
  has "$out" "warning:" "$failure failure warning"
  has "$out" "varde setup watch --stop --remove-index --repo" "$failure one-line fix"
  [[ ! -e "$(wt "$id")" ]] || fail "$failure failure prevented worktree cleanup"
done

# Ignored-only cleanup must leave tracked edits and untracked files untouched.
make_worker tracked
echo modified > "$(wt tracked)/tracked.txt"
  export WATCH_FAILURE=""
run 1 tracked
has "$out" "uncommitted changes" "tracked edits refused"
[[ -d "$(wt tracked)" && "$(cat "$(wt tracked)/tracked.txt")" == modified ]] \
  || fail "tracked edit was discarded"

make_worker untracked
echo scratch > "$(wt untracked)/scratch.txt"
run 1 untracked
has "$out" "uncommitted changes" "untracked file refused"
[[ -d "$(wt untracked)" && -f "$(wt untracked)/scratch.txt" ]] \
  || fail "untracked file was discarded"

echo "PASS: worktree-cleanup-index"
