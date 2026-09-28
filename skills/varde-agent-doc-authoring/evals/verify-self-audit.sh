#!/usr/bin/env bash
set -euo pipefail
: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"

# Optional argument: exact workspace-relative Markdown report path.
# Without it, retain root-level discovery for existing callers.
python3 - "$@" <<'PY'
import json
import os
from pathlib import Path
import re
import sys

assertion = 'The report exists as a new markdown file in the workspace and contains a sequentially numbered inventory beginning at 1'
root = Path(os.environ['EVAL_SANDBOX_DIR']).resolve()
run_start = int(os.environ.get('EVAL_RUN_START', '0'))
pattern = re.compile(r'^(?:#{1,6}\s+)?(\d+)[.)]\s+|^\|\s*(\d+)\s*\|')
fence_pattern = re.compile(r'^ {0,3}(`{3,}|~{3,})')


def inventory_count(text):
    count = best = 0
    fence = None
    for line in text.splitlines():
        marker = fence_pattern.match(line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        match = pattern.match(line)  # Anchored: nested lists and indented code do not count.
        if not match:
            continue
        number = int(match[1] or match[2])
        count = 1 if number == 1 else count + 1 if count and number == count + 1 else 0
        best = max(best, count)
    return best


def verify(report):
    resolved = report.resolve()
    if not resolved.is_relative_to(root) or report.suffix != '.md':
        return False, 'Report must be a Markdown file within the workspace'
    if any(p.is_symlink() for p in (report, *report.parents) if p != root):
        return False, 'Report path must not use symlinks'
    if not report.is_file():
        return False, 'Report file is missing'
    if report.stat().st_mtime < run_start:
        return False, 'Report predates the run'
    count = inventory_count(report.read_text())
    if count < 2:
        return False, 'No top-level inventory has at least two consecutive entries beginning at 1'
    return True, f'{report.relative_to(root)} contains {count} consecutive top-level inventory entries beginning at 1'


passed = False
evidence = 'No new Markdown report was found in the workspace'
if len(sys.argv) > 2 or (len(sys.argv) == 2 and Path(sys.argv[1]).is_absolute()):
    evidence = 'Supply at most one workspace-relative report path'
else:
    candidates = [root / sys.argv[1]] if len(sys.argv) == 2 else sorted(root.glob('*.md'))
    for report in candidates:
        try:
            passed, evidence = verify(report)
        except (OSError, UnicodeError, ValueError) as exc:
            evidence = f'Could not verify report: {exc}'
        if passed:
            break
print(json.dumps({'results': [{'assertion': assertion, 'verdict': 'PASS' if passed else 'FAIL', 'evidence': evidence}]}))
PY
