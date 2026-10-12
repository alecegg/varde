#!/usr/bin/env bash
set -euo pipefail
skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$skills_dir" <<'PY'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
def text(relative):
    return re.sub(r'\s+', ' ', (root / relative).read_text())

# B-wt-1: ownership is checked once per task commit, at integration.
tasks = text('varde-change/references/build-orchestrate-tasks.md')
assert 'check-task-ownership' in tasks

# B-rev-2: one review.md with a per-finding status; the fixer applies every fix
# except intended-behaviour changes, which go to the user grouped; deferred
# findings go to the deferred store; one fixes-only re-review blocks only for
# critical or high new findings. The finish path delegates to this rule.
finish = text('varde-change/references/build-finish.md')
fix = text('varde-review/references/fix.md')
for phrase in (
    'one `review.md` holds every finding with a status',
    'verify the finding is real',
    "apply every fix that keeps the plan's intended behaviour",
    'deferred store',
    'one fixes-only re-review',
    'block only if critical or high',
    'two repair rounds',
    'running them through planning',
):
    assert phrase in fix.lower(), f'fix.md omits {phrase!r}'

# The doc-authoring rule lives once in review-gates.md; the finish path keeps no
# copy, and no removed escalation, isolated-run or milestone-handoff text.
for cut in ('varde-agent-doc-authoring', 'escalate-deferred', 'isolated run', 'handoff'):
    assert cut not in finish.lower(), f'build-finish.md still contains {cut!r}'
print('PASS: integration ownership and approved-fix routing remain explicit')
PY
