#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT_DIR/varde-change/scripts/check-task-ownership.py"
WORK="${TMPDIR:-/tmp}/task-ownership.$$"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

REPO="$WORK/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@example.com
git -C "$REPO" config user.name t
git -C "$REPO" config commit.gpgsign false
mkdir -p "$REPO/src" "$REPO/tasks"
echo base >"$REPO/src/mod.txt"
echo old >"$REPO/src/old.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm base

# write_task <name> <frontmatter-lines...>
write_task() {
  local name="$1"
  shift
  { echo "---"; printf '%s\n' "$@"; echo "---"; echo "body"; } >"$REPO/tasks/$name.md"
}

commit_all() {
  git -C "$REPO" add -A
  git -C "$REPO" commit -qm "$1"
  git -C "$REPO" rev-parse HEAD
}

# run <task> <sha> -> sets OUT and CODE
run() {
  CODE=0
  OUT="$(python3 "$SCRIPT" --task "$REPO/tasks/$1.md" --commit "$2" --repo-root "$REPO" 2>&1)" || CODE=$?
}

expect() {
  local label="$1" want_code="$2" want_text="$3"
  [ "$CODE" -eq "$want_code" ] || fail "$label: exit $CODE, want $want_code: $OUT"
  grep -q -- "$want_text" <<<"$OUT" || fail "$label: output lacks $want_text: $OUT"
}

# 1. modifies + creates + rename, all in scope -> ok
write_task t1 "status: in_progress" "modifies:" "- src/mod.txt" "creates:" "- src/new.txt" "renames:" "- src/old.txt -> src/moved.txt"
echo changed >"$REPO/src/mod.txt"
echo new >"$REPO/src/new.txt"
git -C "$REPO" mv src/old.txt src/moved.txt
sha="$(commit_all in-scope)"
run t1 "$sha"
expect "in-scope" 0 '"status": "ok"'

# 2. stray path -> stray, exact path, exit 2
write_task t2 "status: in_progress" "modifies:" "- src/mod.txt"
echo more >"$REPO/src/mod.txt"
echo stray >"$REPO/src/extra.txt"
sha="$(commit_all stray)"
run t2 "$sha"
expect "stray" 2 '"status": "stray"'
grep -q '"src/extra.txt"' <<<"$OUT" || fail "stray: exact path missing: $OUT"

# 3. commit touching only the task file -> ok
write_task t3 "status: in_progress" "modifies:" "- src/mod.txt"
echo progress >>"$REPO/tasks/t3.md"
sha="$(commit_all task-only)"
run t3 "$sha"
expect "task-file-only" 0 '"status": "ok"'

# 4. no ownership fields -> skipped
write_task t4 "status: in_progress"
echo x >"$REPO/src/any.txt"
sha="$(commit_all no-fields)"
run t4 "$sha"
expect "no-fields" 0 '"status": "skipped"'

# 5. kind: spike -> skipped
write_task t5 "status: in_progress" "kind: spike" "modifies:" "- src/mod.txt"
echo y >"$REPO/src/spike.txt"
sha="$(commit_all spike)"
run t5 "$sha"
expect "spike" 0 '"status": "skipped"'

# 6. merge commit -> merge_commit error, exit 1
base="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" checkout -q -b side
echo s >"$REPO/src/side.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm side
git -C "$REPO" checkout -q -
echo m >"$REPO/src/main.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm mainline
git -C "$REPO" merge -q --no-ff side -m merge
sha="$(git -C "$REPO" rev-parse HEAD)"
write_task t6 "status: in_progress" "modifies:" "- src/mod.txt"
run t6 "$sha"
expect "merge" 1 'merge_commit'

# 7. non-ASCII path is reported unquoted
write_task t7 "status: in_progress" "modifies:" "- src/mod.txt"
echo u >"$REPO/src/café.txt"
sha="$(commit_all non-ascii)"
run t7 "$sha"
expect "non-ascii" 2 'src/caf\\u00e9.txt'

# 8. root commit reports its files
ROOT_REPO="$WORK/root"
mkdir -p "$ROOT_REPO"
git -C "$ROOT_REPO" init -q
git -C "$ROOT_REPO" config user.email t@example.com
git -C "$ROOT_REPO" config user.name t
git -C "$ROOT_REPO" config commit.gpgsign false
echo r >"$ROOT_REPO/only.txt"
git -C "$ROOT_REPO" add -A
git -C "$ROOT_REPO" commit -qm root
{ echo "---"; echo "modifies:"; echo "- other.txt"; echo "---"; } >"$WORK/root-task.md"
CODE=0
OUT="$(python3 "$SCRIPT" --task "$WORK/root-task.md" --commit "$(git -C "$ROOT_REPO" rev-parse HEAD)" --repo-root "$ROOT_REPO" 2>&1)" || CODE=$?
expect "root commit" 2 '"only.txt"'

echo "task-ownership: ok"
