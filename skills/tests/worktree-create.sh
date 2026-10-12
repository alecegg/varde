#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CREATE_SCRIPT="$ROOT_DIR/varde-change/scripts/worktree-create.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test_root="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/wt-create.XXXXXX")" && pwd -P)"
trap 'rm -rf "$test_root"' EXIT
git -C "$test_root" init -q -b main
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm base
base="$(git -C "$test_root" rev-parse HEAD)"

fresh="$(cd "$test_root" && "$CREATE_SCRIPT" --fresh worker "$base")" || fail "fresh worktree was not created"
worker="$test_root/.varde/worktrees/worker"
[[ "$fresh" == *"path=$worker"* && "$fresh" == *"branch=worktree/worker"* && "$fresh" == *'created=true'* ]] || fail "fresh output is incomplete: $fresh"
[[ "$(git -C "$worker" rev-parse HEAD)" == "$base" && -z "$(git -C "$worker" status --porcelain)" ]] || fail "fresh worktree is not clean at the base"

result=0
(cd "$test_root" && "$CREATE_SCRIPT" --fresh worker "$base" >/dev/null 2>&1) || result=$?
[[ "$result" == 3 ]] || fail "existing worktree/branch was not refused"

result=0
(cd "$test_root" && "$CREATE_SCRIPT" --fresh bad-base does-not-exist >/dev/null 2>&1) || result=$?
[[ "$result" == 2 ]] || fail "unresolvable base was not reported as exit 2"

result=0
(cd "$test_root" && "$CREATE_SCRIPT" --fresh >/dev/null 2>&1) || result=$?
[[ "$result" == 1 ]] || fail "missing id was not a usage error"

# Plan bootstrap names a committed base while preserving staged, unstaged and
# untracked origin work; the created worktree is clean at that base.
printf 'staged\n' >>"$test_root/state.txt"
git -C "$test_root" add state.txt
printf 'unstaged\n' >>"$test_root/state.txt"
printf 'untracked\n' >"$test_root/notes.txt"
origin_diff="$(git -C "$test_root" diff --binary HEAD)"
origin_index="$(git -C "$test_root" diff --cached --binary)"
bootstrap="$(cd "$test_root" && "$CREATE_SCRIPT" --plan bootstrap "$base")" || fail "plan bootstrap rejected a dirty origin"
plan_tree="$test_root/.varde/worktrees/bootstrap"
[[ "$bootstrap" == *"path=$plan_tree"* && "$bootstrap" == *'created=true'* ]] || fail "plan bootstrap output is incomplete: $bootstrap"
[[ "$(git -C "$plan_tree" rev-parse HEAD)" == "$base" && -z "$(git -C "$plan_tree" status --porcelain)" ]] || fail "plan bootstrap is not clean at the explicit base"
[[ "$(git -C "$test_root" diff --binary HEAD)" == "$origin_diff" && "$(git -C "$test_root" diff --cached --binary)" == "$origin_index" && -f "$test_root/notes.txt" ]] || fail "plan bootstrap changed origin work"

result=0
(cd "$test_root" && "$CREATE_SCRIPT" --plan missing >/dev/null 2>&1) || result=$?
[[ "$result" == 1 ]] || fail "plan bootstrap accepted a missing explicit base"

# A linked caller is reused by default and isolated with --fresh.
reuse="$(cd "$plan_tree" && "$CREATE_SCRIPT" existing)" || fail "linked caller was not reused"
[[ "$reuse" == *"path=$plan_tree"* && "$reuse" == *'created=false'* ]] || fail "linked caller lost ownership on default reuse: $reuse"
sibling="$(cd "$plan_tree" && "$CREATE_SCRIPT" --fresh sibling "$base")" || fail "fresh allocation from a linked caller failed"
[[ "$sibling" == *"path=$test_root/.varde/worktrees/sibling"* && "$sibling" == *'created=true'* ]] || fail "fresh allocation was not a sibling: $sibling"

# A dirty linked caller cannot allocate a fresh worktree.
printf 'dirty\n' >"$plan_tree/dirty.txt"
result=0
(cd "$plan_tree" && "$CREATE_SCRIPT" --fresh from-dirty "$base" >/dev/null 2>&1) || result=$?
[[ "$result" == 4 && ! -d "$test_root/.varde/worktrees/from-dirty" ]] || fail "fresh allocation accepted a dirty caller"

echo "worktree-create: ok"
