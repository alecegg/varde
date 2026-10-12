#!/usr/bin/env bash
# The plan route's review round is report-only. The planner writes findings to
# notes/plan-review.md, applies them and records the reviewed commit; there is
# no pre-dispatch subject, record, fingerprint or Finalize worktree.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skill="$(cd "$script_dir/../varde-change" && pwd)"
plan_route="$skill/references/plan.md"
plan_template="$skill/assets/PLAN-TEMPLATE.md"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require() { # require <file> <literal>
  grep -qF -- "$2" "$1" || fail "$(basename "$1") is missing: $2"
}

forbid() { # forbid <file> <extended regex>
  if grep -qE -- "$2" "$1"; then
    fail "$(basename "$1") still names: $2"
  fi
}

for file in "$plan_route" "$plan_template"; do
  test -f "$file" || fail "missing $file"
done

require "$plan_route" "notes/plan-review.md"
require "$plan_route" "report-only"
require "$plan_route" "fixes-only"
require "$plan_route" "reviewed_commit"
require "$plan_route" "reviewed_on"
require "$plan_route" "no worktree"

require "$plan_template" "reviewed_commit"
require "$plan_template" "reviewed_on"
require "$plan_template" "shared:"

# The pre-dispatch binding is gone: no subject, record, checkpoint or Finalize
# worktree remains in the plan route.
forbid "$plan_route" 'review (init|check|record)\b'
forbid "$plan_route" '--subject|pre-edit|fingerprint'
forbid "$plan_route" 'plan-path'
forbid "$plan_route" 'worktree-create'

echo "PASS: plan review is report-only with a recorded reviewed commit"
