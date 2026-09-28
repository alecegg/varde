#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
python3 - "$root" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
bad = []
for path in sorted(root.glob('varde-*/SKILL.md')) + sorted(root.glob('varde-*/references/*.md')):
    lines = path.read_text(encoding='utf-8').splitlines()
    for index, line in enumerate(lines):
        if re.search(r'memory-bank/(?:working|knowledge)', line):
            context = ' '.join(lines[max(0, index - 3):index + 1]).lower()
            failure = r'(?:fails?|unavailable|missing|absent|not available)'
            pattern = rf'(?:else|fallback|(?:if|when).{{0,90}}{failure}).{{0,200}}memory-bank/'
            if re.search(pattern, context):
                bad.append(f'{path}:{index + 1}')
if bad:
    print('Storage fallback instructions are forbidden:', file=sys.stderr)
    print('\n'.join(bad), file=sys.stderr)
    sys.exit(1)
print('No guessed memory-bank storage fallbacks in shipped instructions.')
PY
