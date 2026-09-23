#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for script in \
  "$ROOT_DIR/varde-change/scripts/worktree-merge.sh" \
  "$ROOT_DIR/varde-review/scripts/worktree-merge.sh" \
  "$ROOT_DIR/varde-docs/scripts/worktree-merge.sh"; do
  test_root="$(mktemp -d)"
  git -C "$test_root" init -q
  git -C "$test_root" config user.email test@example.com
  git -C "$test_root" config user.name Test
  git -C "$test_root" branch -M main
  printf 'base\n' >"$test_root/state.txt"
  git -C "$test_root" add state.txt
  git -C "$test_root" commit -qm initial
  git -C "$test_root" branch destination
  git -C "$test_root" checkout -qb worktree/sample
  printf 'worktree\n' >>"$test_root/state.txt"
  git -C "$test_root" add state.txt
  git -C "$test_root" commit -qm worktree
  git -C "$test_root" checkout -q main

  before_main="$(git -C "$test_root" rev-parse main)"
  before_destination="$(git -C "$test_root" rev-parse destination)"
  output_file="$test_root/output.txt"
  set +e
  (
    cd "$test_root"
    "$script" sample destination >"$output_file" 2>&1
  )
  result=$?
  set -e

  [ "$result" -eq 4 ] || fail "$script accepted a different merge target"
  [ "$(git -C "$test_root" rev-parse main)" = "$before_main" ] ||
    fail "$script changed the current branch on target mismatch"
  [ "$(git -C "$test_root" rev-parse destination)" = "$before_destination" ] ||
    fail "$script changed the requested target on mismatch"
  grep -F 'not the currently checked-out branch' "$output_file" >/dev/null ||
    fail "$script omitted the target mismatch error"

  rm -rf "$test_root"
done

echo "worktree merge destination tests passed"
