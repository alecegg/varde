#!/usr/bin/env bash
# Exercise varde-review scope scripts in a temporary git repo.
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

for script in change-ranges.sh review-scope.sh; do
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

# Diff headers: an added line starting with "++ " and a file name with a space.
mkdir -p sub
git add -A && git commit -qm "range fixtures"
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

# Diff bytes include untracked file contents, but not whole tracked files.
python3 - <<'PYDATA'
from pathlib import Path
Path("large-ledger.txt").write_text(("x\n") * 100_000)
PYDATA
git add large-ledger.txt && git commit -qm "large ledger fixture"
python3 - <<'PYDATA'
from pathlib import Path
p = Path("large-ledger.txt")
s = p.read_text()
p.write_text("y\n" + s[2:])
PYDATA
out="$($SCRIPTS/review-scope.sh diff)"
diff_bytes="$(awk -F '\t' '$1 == "# bytes" { print $2 }' <<< "$out")"
[ "$diff_bytes" -lt 2000 ] || fail "tracked large file inflated diff bytes: $diff_bytes"
grep -qx $'M\tlarge-ledger.txt' <<< "$out" || fail "large tracked file missing from diff scope"
python3 - <<'PYDATA'
from pathlib import Path
Path("untracked-large.txt").write_text("u" * 10_000)
PYDATA
out="$($SCRIPTS/review-scope.sh diff)"
diff_bytes="$(awk -F '\t' '$1 == "# bytes" { print $2 }' <<< "$out")"
grep -qx $'?\tuntracked-large.txt' <<< "$out" || fail "untracked large file missing from diff scope"
[ "$diff_bytes" -ge 10000 ] || fail "untracked file bytes were not counted: $diff_bytes"
area_out="$($SCRIPTS/review-scope.sh area)"
area_bytes="$(awk -F '\t' '$1 == "# bytes" { print $2 }' <<< "$area_out")"
[ "$area_bytes" -ge 200000 ] || fail "area mode stopped counting tracked file bytes: $area_bytes"

echo "PASS: review scope and change ranges"
