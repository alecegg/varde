#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CREATE_SCRIPT="$ROOT_DIR/varde-change/scripts/worktree-create.sh"
MERGE_SCRIPT="$ROOT_DIR/varde-change/scripts/worktree-merge.sh"
CLEANUP_SCRIPT="$ROOT_DIR/varde-change/scripts/worktree-cleanup.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for script in \
  "$ROOT_DIR/varde-change/scripts/worktree-merge.sh"; do
  test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-dest.XXXXXX")"
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

# Dirty worktree: worktree-merge.sh must refuse to merge and must not commit
# on the caller's behalf (#157).
for script in \
  "$ROOT_DIR/varde-change/scripts/worktree-merge.sh"; do
  test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-dirty.XXXXXX")"
  git -C "$test_root" init -q
  git -C "$test_root" config user.email test@example.com
  git -C "$test_root" config user.name Test
  git -C "$test_root" branch -M main
  printf 'base\n' >"$test_root/state.txt"
  git -C "$test_root" add state.txt
  git -C "$test_root" commit -qm initial

  worktree_path="$test_root/.varde/worktrees/sample"
  mkdir -p "$(dirname "$worktree_path")"
  git -C "$test_root" worktree add -q -b worktree/sample "$worktree_path" main
  git -C "$worktree_path" commit -q --allow-empty -m "worktree sample"
  printf 'dirty\n' >>"$worktree_path/state.txt"

  before_main="$(git -C "$test_root" rev-parse main)"
  before_branch="$(git -C "$test_root" rev-parse worktree/sample)"
  output_file="$test_root/output.txt"
  set +e
  (
    cd "$test_root"
    "$script" sample main >"$output_file" 2>&1
  )
  result=$?
  set -e

  [ "$result" -eq 5 ] || fail "$script did not exit 5 on a dirty worktree"
  [ "$(git -C "$test_root" rev-parse main)" = "$before_main" ] ||
    fail "$script changed main despite a dirty worktree"
  [ "$(git -C "$test_root" rev-parse worktree/sample)" = "$before_branch" ] ||
    fail "$script committed on the caller's behalf"
  git -C "$worktree_path" diff --quiet -- state.txt &&
    fail "$script's dirty worktree content was committed away"
  grep -F 'uncommitted changes' "$output_file" >/dev/null ||
    fail "$script omitted the dirty-worktree error"

  rm -rf "$test_root"
done

# A later worker failure during integration leaves the target SHA unchanged.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-wave-worker-failure.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
target_sha="$(git -C "$test_root" rev-parse main)"

for id in first later; do
  create_output="$(cd "$test_root" && "$CREATE_SCRIPT" "$id" "$target_sha")"
  worker_path="$(printf '%s\n' "$create_output" | sed -n 's/^path=//p')"
  if [ "$id" = first ]; then
    printf 'first worker\n' >>"$worker_path/state.txt"
    git -C "$worker_path" add state.txt
    git -C "$worker_path" commit -qm 'first worker'
  else
    printf 'unfinished worker\n' >>"$worker_path/state.txt"
  fi
done

create_output="$(cd "$test_root" && "$CREATE_SCRIPT" wave-integration "$target_sha")"
integration_path="$(printf '%s\n' "$create_output" | sed -n 's/^path=//p')"
(
  cd "$integration_path"
  "$MERGE_SCRIPT" first >/dev/null
)

before_target="$(git -C "$test_root" rev-parse main)"
[ "$before_target" = "$target_sha" ] || fail "worker setup changed the target SHA"
[ -n "$(git -C "$test_root" status --porcelain)" ] && fail "worker failure fixture dirtied target checkout"
merge_output="$test_root/later-merge.txt"
set +e
(
  cd "$integration_path"
  "$MERGE_SCRIPT" later >"$merge_output" 2>&1
)
result=$?
set -e
[ "$result" -eq 5 ] || fail "later failed worker exited $result, expected 5"
[ "$(git -C "$test_root" rev-parse main)" = "$before_target" ] ||
  fail "a later worker failure advanced the target SHA"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/first || fail "successful worker recovery ref was lost"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/later || fail "failed worker recovery ref was lost"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/wave-integration ||
  fail "partial integration recovery ref was lost"
grep -F 'uncommitted changes' "$merge_output" >/dev/null || fail "failed worker reason was not reported"
rm -rf "$test_root"

# A combined verification failure retains integration refs and leaves target unchanged.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-wave-verify-failure.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
target_sha="$(git -C "$test_root" rev-parse main)"

for id in first second; do
  create_output="$(cd "$test_root" && "$CREATE_SCRIPT" "$id" "$target_sha")"
  worker_path="$(printf '%s\n' "$create_output" | sed -n 's/^path=//p')"
  printf '%s worker\n' "$id" >"$worker_path/$id.txt"
  git -C "$worker_path" add "$id.txt"
  git -C "$worker_path" commit -qm "$id worker"
done

create_output="$(cd "$test_root" && "$CREATE_SCRIPT" wave-integration "$target_sha")"
integration_path="$(printf '%s\n' "$create_output" | sed -n 's/^path=//p')"
(
  cd "$integration_path"
  "$MERGE_SCRIPT" first >/dev/null
  "$MERGE_SCRIPT" second >/dev/null
)
before_target="$(git -C "$test_root" rev-parse main)"
integration_sha="$(git -C "$test_root" rev-parse worktree/wave-integration)"
set +e
(cd "$integration_path" && test -f required-verification-marker)
verification_status=$?
set -e
[ "$verification_status" -ne 0 ] || fail "verification failure fixture unexpectedly passed"
[ "$(git -C "$test_root" rev-parse main)" = "$before_target" ] ||
  fail "failed combined verification advanced the target SHA"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/wave-integration ||
  fail "integration recovery ref was lost after verification failure"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/first || fail "first worker recovery ref was lost"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/second || fail "second worker recovery ref was lost"

# A later passing verification advances the target to the integration commit.
test -f "$integration_path/first.txt" && test -f "$integration_path/second.txt" ||
  fail "integration worktree lost merged worker changes"
git -C "$test_root" merge --ff-only worktree/wave-integration >/dev/null
[ "$(git -C "$test_root" rev-parse main)" = "$integration_sha" ] ||
  fail "successful integration did not advance the target to the verified commit"
rm -rf "$test_root"

# Cleanup resolves worktrees through the shared Git registry, including when
# invoked from a different linked worktree, and removes only merged clean work.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-linked.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
integration_path="$test_root/.varde/worktrees/integration"
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b integration "$integration_path" main
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'merged worker\n' >"$sample_path/worker.txt"
git -C "$sample_path" add worker.txt
git -C "$sample_path" commit -qm 'sample worker'
git -C "$integration_path" merge --ff-only worktree/sample >/dev/null
cleanup_output="$test_root/cleanup-linked.txt"
set +e
(cd "$integration_path" && "$CLEANUP_SCRIPT" sample >"$cleanup_output" 2>&1)
result=$?
set -e
[ "$result" -eq 0 ] || fail "cleanup from another linked worktree exited $result: $(cat "$cleanup_output")"
[ ! -e "$sample_path" ] || fail "cleanup left the registered sample worktree on disk"
if git -C "$test_root" worktree list --porcelain | grep -Fqx "worktree $sample_path"; then
  fail "cleanup left the registered sample worktree in Git's registry"
fi
if git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/sample; then
  fail "cleanup left the merged sample branch"
fi
rm -rf "$test_root"

# Cleanup trusts the caller's verified HEAD ancestry even when Git's branch
# deletion policy sees a lagging configured upstream.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-lagging-upstream.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" branch -M main
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
git -C "$test_root" remote add origin "$test_root/origin.git"
git -C "$test_root" update-ref refs/remotes/origin/main "$(git -C "$test_root" rev-parse main)"
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'merged worker\n' >"$sample_path/worker.txt"
git -C "$sample_path" add worker.txt
git -C "$sample_path" commit -qm 'sample worker'
git -C "$test_root" branch --set-upstream-to=origin/main worktree/sample >/dev/null
git -C "$test_root" merge --ff-only worktree/sample >/dev/null
cleanup_output="$test_root/cleanup-lagging-upstream.txt"
set +e
(cd "$test_root" && "$CLEANUP_SCRIPT" sample >"$cleanup_output" 2>&1)
result=$?
set -e
[ "$result" -eq 0 ] || fail "cleanup rejected a branch merged to caller HEAD because its upstream lagged: $(cat "$cleanup_output")"
[ ! -e "$sample_path" ] || fail "cleanup left the merged worktree with a lagging upstream"
if git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/sample; then
  fail "cleanup left the merged branch with a lagging upstream"
fi
rm -rf "$test_root"

# A ref that changes after the preflight is retained by compare-and-delete.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-stale-ref.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" branch -M main
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'merged worker\n' >"$sample_path/worker.txt"
git -C "$sample_path" add worker.txt
git -C "$sample_path" commit -qm 'sample worker'
git -C "$test_root" merge --ff-only worktree/sample >/dev/null
git -C "$test_root" commit --allow-empty -qm 'concurrent branch advance'
race_sha="$(git -C "$test_root" rev-parse HEAD)"
git_bin_dir="$test_root/git-bin"
mkdir "$git_bin_dir"
real_git="$(command -v git)"
cat >"$git_bin_dir/git" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == update-ref && "${2:-}" == -d && "${3:-}" == refs/heads/worktree/sample ]]; then
  "$REAL_GIT" update-ref "$3" "$RACE_SHA"
fi
exec "$REAL_GIT" "$@"
EOF
chmod +x "$git_bin_dir/git"
cleanup_output="$test_root/cleanup-stale-ref.txt"
set +e
(
  cd "$test_root"
  PATH="$git_bin_dir:$PATH" REAL_GIT="$real_git" RACE_SHA="$race_sha" \
    "$CLEANUP_SCRIPT" sample >"$cleanup_output" 2>&1
)
result=$?
set -e
[ "$result" -ne 0 ] || fail "cleanup reported success after the branch ref changed"
[ ! -e "$sample_path" ] || fail "cleanup did not remove the verified worktree before reporting the ref change"
[ "$(git -C "$test_root" rev-parse refs/heads/worktree/sample)" = "$race_sha" ] ||
  fail "cleanup deleted or changed the ref that advanced after preflight"
grep -F 'changed after preflight' "$cleanup_output" >/dev/null ||
  fail "cleanup did not explain that the branch ref changed after preflight"
rm -rf "$test_root"

# Ignored local data is preserved by normal cleanup and removed only after an
# explicit discard.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-ignored.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
printf 'local-only.txt\n' >"$test_root/.gitignore"
git -C "$test_root" add state.txt .gitignore
git -C "$test_root" commit -qm initial
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'keep this ignored data\n' >"$sample_path/local-only.txt"
cleanup_output="$test_root/cleanup-ignored.txt"
set +e
(cd "$test_root" && "$CLEANUP_SCRIPT" sample >"$cleanup_output" 2>&1)
result=$?
set -e
ignored_refusal=false
if [ "$result" -ne 0 ] && [ -d "$sample_path" ] &&
  [ "$(cat "$sample_path/local-only.txt" 2>/dev/null || true)" = 'keep this ignored data' ] &&
  grep -F 'ignored files' "$cleanup_output" >/dev/null; then
  ignored_refusal=true
fi
if [ -d "$sample_path" ]; then
  cleanup_output="$test_root/cleanup-ignored-discard.txt"
  set +e
  (cd "$test_root" && "$CLEANUP_SCRIPT" --discard sample >"$cleanup_output" 2>&1)
  discard_result=$?
  set -e
  if [ "$discard_result" -ne 0 ] || [ -e "$sample_path/local-only.txt" ] || [ -e "$sample_path" ]; then
    ignored_discard=false
  else
    ignored_discard=true
  fi
else
  ignored_discard=false
fi
rm -rf "$test_root"
[ "$ignored_refusal" = true ] || fail "normal cleanup did not refuse and preserve ignored data"
[ "$ignored_discard" = true ] || fail "explicit discard did not remove the ignored data and worktree"

# Dirty work is retained even when its branch has already been merged.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-dirty.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'committed worker\n' >"$sample_path/worker.txt"
git -C "$sample_path" add worker.txt
git -C "$sample_path" commit -qm 'sample worker'
git -C "$test_root" merge --ff-only worktree/sample >/dev/null
printf 'uncommitted\n' >>"$sample_path/state.txt"
cleanup_output="$test_root/cleanup-dirty.txt"
set +e
(cd "$test_root" && "$CLEANUP_SCRIPT" sample >"$cleanup_output" 2>&1)
result=$?
set -e
[ "$result" -ne 0 ] || fail "cleanup accepted a dirty worktree"
[ -d "$sample_path" ] || fail "cleanup removed a dirty worktree"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/sample || fail "cleanup removed a dirty worktree's branch"
grep -F 'uncommitted changes' "$cleanup_output" >/dev/null || fail "dirty cleanup refusal omitted its reason"
rm -rf "$test_root"

# Clean but unmerged work is retained.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-unmerged.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'unmerged worker\n' >"$sample_path/worker.txt"
git -C "$sample_path" add worker.txt
git -C "$sample_path" commit -qm 'unmerged sample worker'
cleanup_output="$test_root/cleanup-unmerged.txt"
set +e
(cd "$test_root" && "$CLEANUP_SCRIPT" sample >"$cleanup_output" 2>&1)
result=$?
set -e
[ "$result" -ne 0 ] || fail "cleanup accepted an unmerged branch"
[ -d "$sample_path" ] || fail "cleanup removed an unmerged worktree"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/sample || fail "cleanup removed an unmerged branch"
grep -F 'not merged' "$cleanup_output" >/dev/null || fail "unmerged cleanup refusal omitted its reason"
rm -rf "$test_root"

# A branch without a matching worktree, and a detached worktree without its
# conventional branch, must not be mistaken for registered cleanup targets.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-absent.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
git -C "$test_root" branch worktree/orphan main
detached_path="$test_root/.varde/worktrees/detached"
git -C "$test_root" worktree add -q --detach "$detached_path" main
for id in orphan detached; do
  cleanup_output="$test_root/cleanup-$id.txt"
  set +e
  (cd "$test_root" && "$CLEANUP_SCRIPT" "$id" >"$cleanup_output" 2>&1)
  result=$?
  set -e
  [ "$result" -ne 0 ] || fail "cleanup accepted unregistered target '$id'"
done
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/orphan || fail "cleanup deleted an orphan branch"
[ -d "$detached_path" ] || fail "cleanup removed a detached worktree with no matching branch"
rm -rf "$test_root"

# A stale registry entry (path removed outside Git) is not treated as an
# absent, clean worktree and does not authorize branch deletion.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-stale.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
stale_path="$test_root/.varde/worktrees/stale"
git -C "$test_root" worktree add -q -b worktree/stale "$stale_path" main
rm -rf "$stale_path"
cleanup_output="$test_root/cleanup-stale.txt"
set +e
(cd "$test_root" && "$CLEANUP_SCRIPT" stale >"$cleanup_output" 2>&1)
result=$?
set -e
[ "$result" -ne 0 ] || fail "cleanup accepted a stale registry entry"
git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/stale || fail "cleanup deleted a branch for a stale registry entry"
grep -F 'unavailable' "$cleanup_output" >/dev/null || fail "stale cleanup refusal omitted its reason"
rm -rf "$test_root"

# Discard is an explicit path for dirty, unmerged work and still verifies both
# the worktree and branch are gone.
test_root="$(mktemp -d "${TMPDIR:-/tmp}/wt-cleanup-discard.XXXXXX")"
git -C "$test_root" init -q
git -C "$test_root" config user.email test@example.com
git -C "$test_root" config user.name Test
git -C "$test_root" branch -M main
printf 'base\n' >"$test_root/state.txt"
git -C "$test_root" add state.txt
git -C "$test_root" commit -qm initial
sample_path="$test_root/.varde/worktrees/sample"
git -C "$test_root" worktree add -q -b worktree/sample "$sample_path" main
printf 'unmerged worker\n' >"$sample_path/worker.txt"
git -C "$sample_path" add worker.txt
git -C "$sample_path" commit -qm 'unmerged sample worker'
printf 'dirty\n' >>"$sample_path/state.txt"
cleanup_output="$test_root/cleanup-discard.txt"
set +e
(cd "$test_root" && "$CLEANUP_SCRIPT" --discard sample >"$cleanup_output" 2>&1)
result=$?
set -e
[ "$result" -eq 0 ] || fail "explicit discard exited $result: $(cat "$cleanup_output")"
[ ! -e "$sample_path" ] || fail "explicit discard left the worktree on disk"
if git -C "$test_root" worktree list --porcelain | grep -Fqx "worktree $sample_path"; then
  fail "explicit discard left the worktree registered"
fi
if git -C "$test_root" show-ref --verify --quiet refs/heads/worktree/sample; then
  fail "explicit discard left the branch"
fi
rm -rf "$test_root"

echo "worktree merge destination tests passed"
