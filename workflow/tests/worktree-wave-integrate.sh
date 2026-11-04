#!/usr/bin/env bash
# Slower integration regression cases for worktree-wave.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/wave-fixture.sh"

# An executable branch CLI suppresses the installed-varde warning.
mkdir -p "$plan/.venv/bin"
printf '/.venv/\n' >> "$repo/.git/info/exclude"
cat > "$plan/.venv/bin/varde" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$plan/.venv/bin/varde"
git -C "$plan" add -f .venv/bin/varde
git -C "$plan" commit -q -m 'add built branch varde fixture'
task_bin="$TEST_ROOT/tasks/bin.md"; write_task "$task_bin" bin.txt
run 0 start plan-wb bin --task "bin=$task_bin"
commit_in bin bin.txt built
run 5 integrate plan-wb --check "test -f bin.txt && false"
! grep -q 'warning: .venv/bin/varde is missing' <<<"$out" || fail "built branch varde still warned"
commit_in bin bin.txt fixed
run 0 integrate plan-wb --check 'test -f bin.txt'
run 0 release plan-wb
rm -rf "$plan/.venv"
git -C "$plan" add -u .venv/bin/varde
git -C "$plan" commit -q -m 'remove built branch varde fixture'

# --- Wave plan-w4: a failing batch bisects to the culprit -------------------------
base4="$(git rev-parse HEAD)"
task_ba="$TEST_ROOT/tasks/ba.md"; write_task "$task_ba" ba.txt
task_bb="$TEST_ROOT/tasks/bb.md"; write_task "$task_bb" bb.txt
task_bc="$TEST_ROOT/tasks/bc.md"; write_task "$task_bc" bc.txt
task_bd="$TEST_ROOT/tasks/bd.md"; write_task "$task_bd" bd.txt
run 0 start plan-w4 ba bb bc bd --task "ba=$task_ba" --task "bb=$task_bb" --task "bc=$task_bc" --task "bd=$task_bd"
commit_in ba ba.txt a
commit_in bb bb.txt b
commit_in bc bc.txt c
commit_in bd bd.txt d
bisect_check="echo gate >> '$TEST_ROOT/bisect-count'; test -f ba.txt && test -f bb.txt && test ! -f bc.txt"
run 5 integrate plan-w4 --check "$bisect_check"
has "$out" "warning: .venv/bin/varde is missing; integrated check will use the installed varde; run uv sync --locked --all-packages" "missing branch varde warning"
has "$out" "culprit=bc" "bisect culprit"
has "$out" "untouched_remainder=bc bd" "bisect untouched remainder"
[[ "$(git rev-parse HEAD)" == "$base4" ]] || fail "failed batch moved the plan branch"
bisect_tip="$(git rev-parse worktree/bb)"
has "$out" "verified_prefix=$bisect_tip" "exact bisect verified prefix"
[[ "$(git rev-parse worktree/plan-w4-integration)" == "$bisect_tip" ]] || fail "bisection did not leave integration at the passing prefix"
[[ "$(grep -c '^gate$' "$TEST_ROOT/bisect-count")" == 3 ]] || fail "four-task bisection did not use one batch gate and two probes"
commit_in bc bc.txt fixed
run 0 integrate plan-w4 --check 'test -f ba.txt && test -f bb.txt && test -f bc.txt && test -f bd.txt'
[[ "$(git rev-parse HEAD)" == "$(git rev-parse worktree/plan-w4-integration)" ]] || fail "fixed batch did not fast-forward the plan branch"
run 0 release plan-w4

# --- Wave plan-w5: a single-task failure runs one batch gate plus a base probe ---
base5="$(git rev-parse HEAD)"
task_sf="$TEST_ROOT/tasks/sf.md"; write_task "$task_sf" sf.txt
run 0 start plan-w5 sf --task "sf=$task_sf"
commit_in sf sf.txt fail
# The check passes at the base and fails once the task commit lands.
run 5 integrate plan-w5 --check "echo gate >> '$TEST_ROOT/single-count'; test ! -f sf.txt"
has "$out" "culprit=sf" "single-task failure culprit"
[[ "$(grep -c '^gate$' "$TEST_ROOT/single-count")" == 2 ]] || fail "single-task failure did not probe the passing base"
[[ "$(git rev-parse HEAD)" == "$base5" ]] || fail "single-task failure moved the plan branch"
commit_in sf sf.txt fixed
run 0 integrate plan-w5 --check 'test -f sf.txt'
run 0 release plan-w5

# --- Wave plan-w5b: a base that already fails the check blames the base -------------
base5b="$(git rev-parse HEAD)"
task_sfb="$TEST_ROOT/tasks/sfb.md"; write_task "$task_sfb" sfb.txt
run 0 start plan-w5b sfb --task "sfb=$task_sfb"
commit_in sfb sfb.txt fail
run 5 integrate plan-w5b --check "echo gate >> '$TEST_ROOT/base-fail-count'; false"
has "$out" "culprit=base" "base-failure culprit"
! grep -q '^verified_prefix=' "$TEST_ROOT/stdout" || fail "base failure printed a verified prefix"
[[ "$(git rev-parse HEAD)" == "$base5b" ]] || fail "base-failure batch moved the plan branch"
[[ "$(grep -c '^gate$' "$TEST_ROOT/base-fail-count")" == 2 ]] || fail "base failure did not run the batch gate and one base probe"

# --- release removes the worktree with ignored files -------------------------
task_di="$TEST_ROOT/tasks/di.md"; write_task "$task_di" di.txt
run 0 start plan-w6 di --task "di=$task_di"
commit_in di di.txt committed
run 0 integrate plan-w6 --check 'test -f di.txt'
echo generated > "$(wt di)/generated.ignored"
run 0 release plan-w6
! branch_exists worktree/di && [[ ! -d "$(wt di)" ]] || fail "release did not remove the worktree with ignored files"

# A skills-only checkout has no Python CLI package and needs no warning.
git rm -q app/pyproject.toml
git commit -q -m 'remove Python CLI fixture'
task_noclis="$TEST_ROOT/tasks/noclis.md"; write_task "$task_noclis" noclis.txt
run 0 start plan-w-no-clis noclis --task "noclis=$task_noclis"
commit_in noclis noclis.txt skills-only
run 5 integrate plan-w-no-clis --check false
! grep -q 'warning: .venv/bin/varde is missing' <<<"$out" || fail "skills-only wave warned about branch varde"
commit_in noclis noclis.txt fixed
run 0 integrate plan-w-no-clis --check 'test -f noclis.txt'
run 0 release plan-w-no-clis

echo "PASS: worktree-wave-integrate"
