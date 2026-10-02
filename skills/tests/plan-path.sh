#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN_PATH="$SCRIPT_DIR/../varde-change/scripts/plan-path.py"
TEST_ROOT="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/plan-path.XXXXXX")" && pwd -P)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -x "$PLAN_PATH" || fail "plan-path.py is missing or not executable"

today="$(date -u +%Y-%m-%d)"

# Draft: UTC date and collision suffix.
work="$TEST_ROOT/out/working"
first="$("$PLAN_PATH" draft --working "$work" --slug tmp)"
[ "$first" = "$work/plans/$today-tmp-draft" ] || fail "draft path: $first"
second="$("$PLAN_PATH" draft --working "$work" --slug tmp)"
[ "$second" = "$work/plans/$today-tmp-draft-2" ] || fail "collision path: $second"

# Finalize outside a repo: plain move, keeps the draft date, reports ignored.
old="$work/plans/2020-01-02-tmp-draft"
mkdir -p "$old" && echo x > "$old/plan.md"
out="$("$PLAN_PATH" finalize --draft "$old" --slug real)"
[ "$(echo "$out" | sed -n 1p)" = "$work/plans/2020-01-02-real" ] || fail "finalize path: $out"
[ "$(echo "$out" | sed -n 2p)" = "ignored: true" ] || fail "outside repo ignored: $out"
test -f "$work/plans/2020-01-02-real/plan.md" && ! test -e "$old" || fail "outside repo move"

# Refuses an existing destination.
mkdir -p "$work/plans/2020-01-02-again-draft"
mkdir -p "$work/plans/2020-01-02-real2"
if "$PLAN_PATH" finalize --draft "$work/plans/2020-01-02-again-draft" --slug real2 2>/dev/null; then
  fail "existing destination was not refused"
fi
test -d "$work/plans/2020-01-02-again-draft" || fail "refused draft was moved"

# Inside a repo: tracked drafts use git mv, ignored drafts use a plain move.
repo="$TEST_ROOT/repo"
mkdir -p "$repo/plans/2020-01-02-t-draft" "$repo/local/2020-01-02-i-draft"
git -C "$repo" init -q
echo x > "$repo/plans/2020-01-02-t-draft/plan.md"
echo x > "$repo/local/2020-01-02-i-draft/plan.md"
echo 'local/' > "$repo/.gitignore"
git -C "$repo" add .gitignore plans
git -C "$repo" -c user.name=t -c user.email=t@t commit -qm init

out="$("$PLAN_PATH" finalize --draft "$repo/plans/2020-01-02-t-draft" --slug t)"
[ "$(echo "$out" | sed -n 2p)" = "ignored: false" ] || fail "tracked ignored flag: $out"
git -C "$repo" status --porcelain | grep -q '^R ' || fail "tracked plan was not renamed with git mv"

out="$("$PLAN_PATH" finalize --draft "$repo/local/2020-01-02-i-draft" --slug i)"
[ "$(echo "$out" | sed -n 2p)" = "ignored: true" ] || fail "ignored flag: $out"
test -f "$repo/local/2020-01-02-i/plan.md" || fail "ignored plan move"

echo "plan-path: pass"
