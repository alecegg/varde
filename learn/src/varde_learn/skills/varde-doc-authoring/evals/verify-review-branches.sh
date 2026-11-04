#!/usr/bin/env bash
set -euo pipefail
: "${EVAL_ID:?EVAL_ID is required}"
: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"
: "${EVAL_SKILL_DIR:?EVAL_SKILL_DIR is required}"
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ['EVAL_SANDBOX_DIR'])
relative = Path('evals/fixtures/review-guidance/AGENTS.md')
target = root / relative
baseline = (Path(os.environ['EVAL_SKILL_DIR']) / relative).read_bytes()
results = []


def record(assertion, passed, evidence):
    results.append({'assertion': assertion, 'verdict': 'PASS' if passed else 'FAIL', 'evidence': evidence})


actual = target.read_bytes() if target.is_file() and not target.is_symlink() else None
if os.environ['EVAL_ID'] == '4':
    duplicate = b'- Include the release date from the source notes.\n'
    assert baseline.count(duplicate) == 2, 'fixture must contain exactly two duplicate instructions'
    expected = baseline.replace(duplicate, b'', 1)
    record(
        'The target contains exactly one copy of the release-date instruction and all other bytes are preserved',
        actual == expected,
        'Compared target bytes with the immutable fixture minus one duplicate instruction',
    )
elif os.environ['EVAL_ID'] == '5':
    record('The report-only agent review leaves the target unchanged', actual == baseline,
           'Compared target bytes with the immutable fixture')
    before = json.loads((Path(os.environ['EVAL_RUN_DIR']) / 'markdown-before.json').read_text())
    assert isinstance(before, dict), 'invalid Markdown baseline'
    changed = []
    for p in root.rglob('*.md'):
        rel = str(p.relative_to(root))
        if rel == str(relative):
            continue
        if p.is_symlink() or (p.is_file() and before.get(rel) != hashlib.sha256(p.read_bytes()).hexdigest()):
            changed.append(rel)
    record('The agent-initiated review creates or modifies no Markdown report file', not changed,
           'New or changed Markdown outside the target: ' + ', '.join(sorted(changed)) if changed
           else 'No new or changed Markdown outside the supplied target')
else:
    raise ValueError('unsupported EVAL_ID: ' + os.environ['EVAL_ID'])
print(json.dumps({'results': results}))
PY
