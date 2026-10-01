#!/usr/bin/env bash
# Exercise varde-review scope and snapshot scripts in a temporary git repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)/varde-review/scripts"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/review-scope.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}
expect() { # expect <label> <actual> <expected>
  [ "$2" = "$3" ] || fail "$1"$'\n'"expected: $3"$'\n'"actual:   $2"
}

for script in change-ranges.sh snapshot.sh review-scope.sh; do
  test -x "$SCRIPTS/$script" || fail "$script is missing or not executable"
  "$SCRIPTS/$script" --help >/dev/null || fail "$script --help failed"
done

repo="$TEST_ROOT/repo"
git init -q "$repo"
cd "$repo"
git config user.email eval@example.invalid
git config user.name Eval
printf '1\n2\n3\n4\n5\n' > edit.txt
printf 'gone\n' > gone.txt
printf 'keep\n' > keep.txt
printf 'ignored\n' > .gitignore
git add . && git commit -qm seed
git tag v1.0.0
git rm -q gone.txt && git commit -qm "remove gone"
tag_sha="$(git rev-parse v1.0.0)"

# Clean tree: diff scope falls back to the nearest release tag.
out="$("$SCRIPTS/review-scope.sh" diff)"
expect "clean tree targets tag" "$(grep '^# target' <<< "$out")" $'# target\tv1.0.0...HEAD'
expect "clean tree base" "$(grep '^# base' <<< "$out")" $'# base\t'"$tag_sha"
expect "clean tree files" "$(grep -v '^#' <<< "$out")" $'D\tgone.txt'

# Working-tree changes: edit line 2, append a line, stage one delete-only file.
printf '1\nTWO\n3\n4\n5\n6\n' > edit.txt
printf '' > keep.txt && git add keep.txt
printf 'fresh\n' > new.txt
printf 'x\n' > ignored

expect "default ranges" "$("$SCRIPTS/change-ranges.sh")" $'edit.txt\t2-2,6-6\nnew.txt\tall'
expect "staged ranges" "$("$SCRIPTS/change-ranges.sh" --staged)" ""
expect "named file ranges" "$("$SCRIPTS/change-ranges.sh" -- edit.txt)" $'edit.txt\t2-2,6-6'
expect "ref ranges" "$("$SCRIPTS/change-ranges.sh" --ref v1.0.0 -- edit.txt)" $'edit.txt\t2-2,6-6'
git add edit.txt
expect "staged edit" "$("$SCRIPTS/change-ranges.sh" --staged)" $'edit.txt\t2-2,6-6'

out="$("$SCRIPTS/review-scope.sh" diff)"
expect "dirty target" "$(grep '^# target' <<< "$out")" $'# target\tworking tree vs HEAD'
expect "dirty files" "$(grep -v '^#' <<< "$out")" $'M\tedit.txt\nM\tkeep.txt\n?\tnew.txt'
grep -q $'^# tokens\t[1-9]' <<< "$out" || fail "dirty tokens missing"
out="$("$SCRIPTS/review-scope.sh" diff --ref v1.0.0 -- gone.txt)"
expect "ref narrowed" "$(grep -v '^#' <<< "$out")" $'D\tgone.txt'
out="$("$SCRIPTS/review-scope.sh" area)"
expect "area files" "$(grep -v '^#' <<< "$out")" $'T\t.gitignore\nT\tedit.txt\nT\tkeep.txt\n?\tnew.txt'
grep -q '^# base' <<< "$out" && fail "area mode must not print a base"

# Snapshot and restore, one file at a time, including a file created later.
backup="$TEST_ROOT/backup"
mkdir -p sub
"$SCRIPTS/snapshot.sh" save "$backup" edit.txt "$repo/sub/made.txt"
printf 'changed\n' > edit.txt
printf 'made\n' > sub/made.txt
"$SCRIPTS/snapshot.sh" save "$backup" edit.txt  # keeps the first snapshot
(cd sub && "$SCRIPTS/snapshot.sh" restore "$backup" edit.txt) >/dev/null
expect "restored edit" "$(cat edit.txt)" $'1\nTWO\n3\n4\n5\n6'
test -f sub/made.txt || fail "restore of one path touched another"
"$SCRIPTS/snapshot.sh" restore "$backup" >/dev/null
test ! -e sub/made.txt || fail "new file was not deleted"
if "$SCRIPTS/snapshot.sh" restore "$backup" keep.txt 2>/dev/null; then
  fail "restore of an unsaved path must fail"
fi
if "$SCRIPTS/snapshot.sh" restore "$TEST_ROOT/no-such-backup" 2>/dev/null; then
  fail "restore from a missing backup dir must fail"
fi
test ! -e "$TEST_ROOT/no-such-backup" || fail "restore created the missing backup dir"

# Paths are normalized, so "./x" and "sub/../x" name the same entry as "x".
backup2="$TEST_ROOT/backup2"
"$SCRIPTS/snapshot.sh" save "$backup2" ./keep.txt
printf 'changed\n' > keep.txt
"$SCRIPTS/snapshot.sh" restore "$backup2" sub/../keep.txt >/dev/null
expect "normalized restore" "$(cat keep.txt)" ""
expect "one manifest entry" "$(cut -f2 "$backup2/manifest")" "keep.txt"

# Symlinks are saved and restored as links, not as their targets' contents.
ln -s keep.txt link.txt
"$SCRIPTS/snapshot.sh" save "$backup2" link.txt
test -L "$backup2/files/link.txt" || fail "save dereferenced a symlink"
rm link.txt && printf 'plain\n' > link.txt
"$SCRIPTS/snapshot.sh" restore "$backup2" link.txt >/dev/null
expect "restored symlink" "$(readlink link.txt)" "keep.txt"
rm link.txt

# Diff headers: an added line starting with "++ " and a file name with a space.
git add -A && git commit -qm "snapshot fixtures"
printf 'a\n' > 'with space.txt' && printf 'x\ny\n' > plus.txt
git add . && git commit -qm "more fixtures"
printf 'a\nb\n' > 'with space.txt'
printf '++ added\nx\ny\nz\n' > plus.txt
expect "tricky ranges" "$("$SCRIPTS/change-ranges.sh")" $'plus.txt\t1-1,4-4\nwith space.txt\t2-2'

# From a subdirectory with no paths, untracked files are listed repo-wide.
printf 'top\n' > top-untracked.txt
out="$(cd sub && "$SCRIPTS/review-scope.sh" area)"
grep -qx $'?\ttop-untracked.txt' <<< "$out" || fail "area from subdir missed a top-level untracked file"
out="$(cd sub && "$SCRIPTS/review-scope.sh" diff)"
grep -qx $'?\ttop-untracked.txt' <<< "$out" || fail "diff from subdir missed a top-level untracked file"
expect "change-ranges from subdir" "$(cd sub && "$SCRIPTS/change-ranges.sh" | grep untracked)" $'top-untracked.txt\tall'

echo "PASS: review scope, change ranges, and snapshot scripts"
