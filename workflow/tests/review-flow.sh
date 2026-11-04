#!/usr/bin/env bash
# Exercise review scope, structure validation, re-check history and conclusion.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$REPO_ROOT/core/tests/lib/repo.sh"
source "$REPO_ROOT/workflow/tests/lib/varde-bin.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/review-flow.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
expect_failure() {
  local label="$1" expected="$2"; shift 2
  local output
  if output="$("$@" 2>&1)"; then fail "$label unexpectedly succeeded"; fi
  [[ "$output" == *"$expected"* ]] || fail "$label did not report $expected: $output"
}

export HOME="$TEST_ROOT/home" XDG_CONFIG_HOME="$TEST_ROOT/config"
export VARDE_CONFIG_DIR="$TEST_ROOT/varde" XDG_DATA_HOME="$TEST_ROOT/data"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$VARDE_CONFIG_DIR" "$XDG_DATA_HOME"
VARDE="$(checkout_varde "$REPO_ROOT")"
SCOPE="$(skill_dir varde-review)/scripts/review-scope.sh"
repo="$TEST_ROOT/repo"
git init -q "$repo"
git -C "$repo" config user.email eval@example.invalid
git -C "$repo" config user.name Eval
mkdir -p "$repo/plans/demo"
printf 'before\n' > "$repo/source.txt"
cat > "$repo/plans/demo/plan.md" <<'EOF'
---
id: demo
type: plan
status: active
---

## Acceptance criteria
- [ ] reviewed
EOF
git -C "$repo" add . && git -C "$repo" commit -qm seed
base="$(git -C "$repo" rev-parse HEAD)"
printf 'after\n' > "$repo/source.txt"

review="$repo/plans/demo/review.md"
head="$base"
cat > "$review" <<EOF
---
type: review
verdict: changes-requested
base: $base
head: $head
---

## [CORRECTNESS-001] Preserve the source value

**Severity:** high
**Status:** open

### Solutions

1. Keep the expected value.

## [DESIGN-002] Consider a simpler name

**Severity:** low
**Status:** open

### Solutions

1. Rename the local variable.
EOF
git -C "$repo" add plans/demo/review.md && git -C "$repo" commit -qm 'fix(CORRECTNESS-001): record review request'
expect_failure 'changes-requested conclude' 'review verdict is changes-requested' \
  "$VARDE" plan conclude "$repo/plans/demo" --repo "$repo"

# The CLI structure check catches both missing sections and repeated IDs.
sed '/### Solutions/,$d' "$review" > "$TEST_ROOT/malformed.md"
expect_failure 'missing Solutions validation' 'missing ### Solutions' \
  "$VARDE" plan validate "$TEST_ROOT/malformed.md"
cat > "$TEST_ROOT/duplicate.md" <<'EOF'
---
type: review
verdict: changes-requested
head: abc
---
## [CODE-001] First
**Severity:** low
**Status:** open
### Solutions
Fix.
## [CODE-001] Second
**Severity:** low
**Status:** open
### Solutions
Fix.
EOF
expect_failure 'duplicate ID validation' 'duplicate finding id CODE-001' \
  "$VARDE" plan validate "$TEST_ROOT/duplicate.md"
cat > "$TEST_ROOT/bad-severity.md" <<'EOF'
---
type: review
verdict: changes-requested
head: abc
---
## [CODE-002] Invalid severity
**Severity:** urgent
**Status:** open
### Solutions
Fix.
EOF
expect_failure 'invalid severity validation' 'CODE-002 has an invalid severity' \
  "$VARDE" plan validate "$TEST_ROOT/bad-severity.md"
cat > "$repo/plans/demo/fixed-high.md" <<EOF
---
type: review
verdict: changes-requested
base: $base
head: $base
---
## [CODE-003] Claimed fixed without a fix
**Severity:** high
**Status:** fixed
### Solutions
Fix.
EOF
expect_failure 'fixed high without matching commit' \
  'CODE-003 is fixed high without a matching fix(CODE-003) commit' \
  "$VARDE" plan validate "$repo/plans/demo/fixed-high.md"

# The fake reviewer re-checks after the finding-specific fix commit.
printf 'expected\n' > "$repo/source.txt"
git -C "$repo" add source.txt
git -C "$repo" commit -qm 'fix(CORRECTNESS-001): preserve source value'
head="$(git -C "$repo" rev-parse HEAD)"
scope="$(cd "$repo" && "$SCOPE" diff --ref "$base")"
[[ "$scope" == *$'# base\t'"$base"* ]] || fail "scope omitted base commit"
[[ "$scope" == *$'M\tsource.txt'* ]] || fail "scope omitted changed file"
python3 - "$review" "$base" "$head" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text().replace("verdict: changes-requested", "verdict: approved")
s = s.replace("head: " + s.split("head: ", 1)[1].splitlines()[0], "head: " + sys.argv[3])
s = s.replace("**Status:** open", "**Status:** fixed", 1)
s = s.replace("## [CORRECTNESS-001]", "## Re-check\n\nThe source fix is present.\n\n## [CORRECTNESS-001]")
p.write_text(s)
PY
(cd "$repo" && "$VARDE" plan validate "$review")
expect_failure 'wrong merged head' 'does not match reviewed head' \
  "$VARDE" plan conclude "$repo/plans/demo" --repo "$repo" --merged "$base"
(cd "$repo" && "$VARDE" plan conclude "$repo/plans/demo" --repo "$repo")
grep -q '^status: completed$' "$repo/plans/demo/plan.md" || fail "plan status not completed"
git -C "$repo" commit --allow-empty -qm 'post-review change'
expect_failure 'commit after reviewed head' 'does not match reviewed head' \
  "$VARDE" plan conclude "$repo/plans/demo" --repo "$repo"
post_review_head="$(git -C "$repo" rev-parse HEAD)"
python3 - "$review" "$post_review_head" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
s = s.replace("head: " + s.split("head: ", 1)[1].splitlines()[0], "head: " + sys.argv[2])
p.write_text(s)
PY
expect_failure 'header-only re-check rejects a non-fix commit' \
  'header-only re-check includes commits' "$VARDE" plan validate "$review"

# A task-only change directory concludes without a plan status write.
task_repo="$TEST_ROOT/task-repo"
git init -q "$task_repo"
git -C "$task_repo" config user.email eval@example.invalid
git -C "$task_repo" config user.name Eval
git -C "$task_repo" commit --allow-empty -qm task-seed
task_head="$(git -C "$task_repo" rev-parse HEAD)"
mkdir -p "$task_repo/change"
printf '%s\n' '---' 'type: review' 'verdict: approved' "head: $task_head" '---' > "$task_repo/change/review.md"
printf '%s\n' '---' 'id: task-only' 'type: task' 'status: todo' '---' > "$task_repo/change/task.md"
(cd "$task_repo" && "$VARDE" plan conclude "$task_repo/change" --repo "$task_repo")
grep -q '^status: todo$' "$task_repo/change/task.md" || fail "task status changed"
mkdir -p "$task_repo/empty-change"
printf '%s\n' '---' 'type: review' 'verdict: approved' "head: $task_head" '---' > "$task_repo/empty-change/review.md"
expect_failure 'conclude requires a plan or task' 'has no plan.md or task.md' \
  "$VARDE" plan conclude "$task_repo/empty-change" --repo "$task_repo"

# A standalone review directory accepts a deferred finding.
standalone="$TEST_ROOT/working/reviews/2026-10-17-demo"
mkdir -p "$standalone"
cat > "$standalone/review.md" <<EOF
---
type: review
verdict: changes-requested
head: $head
---

## [DESIGN-003] Defer cleanup

**Severity:** medium
**Status:** deferred

### Solutions

1. Revisit later.
EOF
"$VARDE" plan validate "$standalone/review.md"
echo "PASS: review flow"
