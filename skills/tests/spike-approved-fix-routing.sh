#!/usr/bin/env bash
set -euo pipefail
skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$skills_dir" <<'PY'
from pathlib import Path
import json
import re
import sys
root = Path(sys.argv[1])
def text(relative):
    return re.sub(r'\s+', ' ', (root / relative).read_text())

dispatch = text('varde-change/references/build.md')
assert '| `parallel` | `execution=auto` (the default)' in dispatch
assert 'Skip the source commit/ownership audit only for spikes' in dispatch
assert 'Before accepting a completed implementation task, compare' in dispatch
assert 'Every `done` implementation task needs a matching source commit' in dispatch
assert 'Before accepting a completed spike, confirm its question/approach/answer' in dispatch
execution = text('varde-change/references/build-execution.md')
assert 'For a spike, commit no source changes' in execution
fix = text('varde-review/references/fix-pass.md')
assert fix.index('process only the supplied `finding_ids`') < fix.index('For each eligible finding:')
assert 'use its concrete approved solution without substituting another' in fix
assert 'Matching approval satisfies this category-only gate' in fix
assert 'missing or mismatched evidence escalates' in fix
assert 'Approval never bypasses spec-conflict, scope, ownership, independent review, or verification checks' in fix
assert 'Preserve recorded decision history on every defer/rejection' in fix
cases = json.loads((root / 'varde-review/evals/evals.json').read_text())['evals']
approved = next(case for case in cases if case['id'] == 3)
unapproved = next(case for case in cases if case['id'] == 13)
assert 'traceable decision evidence' in approved['prompt']
assert 'unselected finding stays untouched' in approved['expected_output']
assert 'no concrete approved solution or traceable user decision evidence' in unapproved['prompt']
assert 'before editing' in unapproved['expected_output']
group = text('varde-change/references/orchestrate.md')
assert group.index('## Approve and activate the group') < group.index('## Delegate children')
assert 'Keep each child\'s own subject and gates' in group
assert 'active group uses `review check --checkpoint resume`' in group
assert group.index('independent entire-group implementation review') < group.index('--checkpoint complete')
assert 'varde-workflow conclude <group-plan.md> --json' in group
assert 'A live nested task binding must be integrated and released' in group
assert 'That checkout is the owning approval repository' in group
assert 'Serial children finish their local gates and tracked state' in group
print('PASS: spike isolation, approved/unapproved bounded fixes and aggregate group routing remain explicit')
PY
