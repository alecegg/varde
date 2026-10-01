#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/../varde-knowledge/scripts/handoff-snapshot.py"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/handoff-snapshot.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -f "$SCRIPT" || fail "handoff-snapshot.py is missing"

make_tree() {
  mkdir -p "$1/dir/nested"
  printf 'alpha\n' >"$1/dir/b.txt"
  printf 'hidden\n' >"$1/dir/.hidden"
  printf 'deep\n' >"$1/dir/nested/a.txt"
  printf '\000\001\377' >"$1/dir/bin.dat"
  printf 'single\n' >"$1/file.md"
  ln -s b.txt "$1/dir/link"
}

# check <tree> <prefix> <target-relative-to-tree...>: run and assert shape.
check() {
  local tree="$1" prefix="$2"
  shift 2
  ( cd "$tree" && python3 -B "$SCRIPT" -- "$@" ) | python3 -c '
import json, sys
prefix = sys.argv[1]
data = json.load(sys.stdin)
snap = data["snapshots"]
assert snap["file.md"] == [{"path": ".", "hash": snap["file.md"][0]["hash"]}], snap["file.md"]
paths = [e["path"] for e in snap["dir"]]
assert paths == [".hidden", "b.txt", "bin.dat", "nested/a.txt"], paths
for entries in snap.values():
    for e in entries:
        assert e["hash"].startswith(prefix), e
assert data["skipped_symlinks"] == ["dir/link"], data["skipped_symlinks"]
' "$prefix" || fail "unexpected output under prefix $prefix"
}

outside="$TEST_ROOT/outside"
mkdir -p "$outside"
make_tree "$outside"
check "$outside" "sha256:" dir file.md

# sha256 must be over raw bytes
expected="$(shasum -a 256 "$outside/file.md" | cut -d' ' -f1)"
got="$(cd "$outside" && python3 -B "$SCRIPT" -- file.md | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshots"]["file.md"][0]["hash"])')"
[ "$got" = "sha256:$expected" ] || fail "sha256 mismatch: $got"

inside="$TEST_ROOT/inside"
mkdir -p "$inside"
git -C "$inside" init -q
make_tree "$inside"
check "$inside" "git-blob:" dir file.md

expected="$(git -C "$inside" hash-object --no-filters -- file.md)"
got="$(cd "$inside" && python3 -B "$SCRIPT" -- file.md | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshots"]["file.md"][0]["hash"])')"
[ "$got" = "git-blob:$expected" ] || fail "git-blob mismatch: $got"

echo "PASS: handoff-snapshot"
