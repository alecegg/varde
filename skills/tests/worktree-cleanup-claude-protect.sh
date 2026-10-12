#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLEANUP_SCRIPT="$ROOT_DIR/varde-change/scripts/worktree-cleanup.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test_root="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/wt-claude-protect.XXXXXX")" && pwd -P)"
read_only_dir=""
read_only_admin_dir=""
read_only_admin_parent=""
cleanup_test_root() {
  if [[ -n "$read_only_admin_dir" && -d "$read_only_admin_dir" ]]; then
    chmod u+w "$read_only_admin_dir" || true
  fi
  if [[ -n "$read_only_admin_parent" && -d "$read_only_admin_parent" ]]; then
    chmod u+w "$read_only_admin_parent" || true
  fi
  if [[ -n "$read_only_dir" && -d "$read_only_dir" ]]; then
    chmod u+w "$read_only_dir" || true
  fi
  rm -rf "$test_root"
}
trap cleanup_test_root EXIT

git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
mkdir -p "$test_root/.claude/skills"
printf 'tracked fixture\n' > "$test_root/.claude/skills/fixture.txt"
git -C "$test_root" add .claude/skills/fixture.txt
git -C "$test_root" commit -qm initial

id="claude-protect"
branch="worktree/$id"
worktree_path="$test_root/.varde/worktrees/$id"
git -C "$test_root" worktree add -q -b "$branch" "$worktree_path" main
worktree_path="$(cd "$worktree_path" && pwd -P)"
branch_oid="$(git -C "$test_root" rev-parse "$branch")"
read_only_dir="$worktree_path/.claude/skills"
chmod u-w "$read_only_dir"

for mode in normal discard; do
  args=("$id")
  [[ "$mode" == discard ]] && args=(--discard "${args[@]}")

  result=0
  if output="$(cd "$test_root" && "$CLEANUP_SCRIPT" "${args[@]}" 2>&1)"; then
    result=0
  else
    result=$?
  fi
  [[ "$result" -eq 1 ]] || fail "$mode cleanup exited $result, expected 1"
  [[ "$output" == *"$read_only_dir"* ]] || fail "$mode cleanup omitted the read-only .claude path: $output"
  [[ "$output" == *"rerun with escalated access"* ]] || fail "$mode cleanup omitted the escalation instruction: $output"
  [[ -d "$worktree_path" ]] || fail "$mode cleanup removed the worktree"
  [[ "$(git -C "$test_root" rev-parse "$branch")" == "$branch_oid" ]] || fail "$mode cleanup changed or deleted the branch"
  git -C "$test_root" worktree list --porcelain | grep -Fqx "worktree $worktree_path" ||
    fail "$mode cleanup unregistered the worktree"

  probes="$(find -P "$worktree_path/.claude" -name '.varde-worktree-cleanup-probe.*' -print)"
  [[ -z "$probes" ]] || fail "$mode cleanup left probe files: $probes"
done

chmod u+w "$read_only_dir"
read_only_dir=""
admin_dir="$(git -C "$worktree_path" rev-parse --path-format=absolute --git-dir)"
read_only_admin_dir="$admin_dir"
chmod u-w "$read_only_admin_dir"

result=0
if output="$(cd "$test_root" && "$CLEANUP_SCRIPT" "$id" 2>&1)"; then
  result=0
else
  result=$?
fi
[[ "$result" -eq 1 ]] || fail "unwritable git admin dir cleanup exited $result, expected 1"
[[ "$output" == *"$admin_dir"* ]] || fail "cleanup omitted the unwritable git admin dir: $output"
[[ -d "$worktree_path" ]] || fail "cleanup removed the worktree with an unwritable git admin dir"
[[ "$(git -C "$test_root" rev-parse "$branch")" == "$branch_oid" ]] ||
  fail "cleanup changed or deleted the branch with an unwritable git admin dir"
git -C "$test_root" worktree list --porcelain | grep -Fqx "worktree $worktree_path" ||
  fail "cleanup unregistered the worktree with an unwritable git admin dir"

chmod u+w "$read_only_admin_dir"
read_only_admin_dir=""
read_only_admin_parent="$(dirname "$admin_dir")"
chmod u-w "$read_only_admin_parent"

result=0
if output="$(cd "$test_root" && "$CLEANUP_SCRIPT" "$id" 2>&1)"; then
  result=0
else
  result=$?
fi
[[ "$result" -eq 1 ]] || fail "unwritable git admin parent cleanup exited $result, expected 1"
[[ "$output" == *"$read_only_admin_parent"* ]] ||
  fail "cleanup omitted the unwritable git admin parent dir: $output"
[[ -d "$worktree_path" ]] || fail "cleanup removed the worktree with an unwritable git admin parent"
[[ "$(git -C "$test_root" rev-parse "$branch")" == "$branch_oid" ]] ||
  fail "cleanup changed or deleted the branch with an unwritable git admin parent"
git -C "$test_root" worktree list --porcelain | grep -Fqx "worktree $worktree_path" ||
  fail "cleanup unregistered the worktree with an unwritable git admin parent"

echo "PASS: worktree cleanup protects .claude paths and git admin dirs"
