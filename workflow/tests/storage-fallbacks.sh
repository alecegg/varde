#!/usr/bin/env bash
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
root="${1:-$REPO_ROOT}"
if [ -d "$root/.git" ] || [ -f "$root/.git" ]; then
  source "$root/core/tests/lib/repo.sh"
  skills=()
  while IFS= read -r skill; do skills+=("$skill"); done < <(skill_dirs)
  if [ "${#skills[@]}" -ne 19 ]; then
    echo "expected 19 source skills, found ${#skills[@]}" >&2
    exit 1
  fi
else
  skills=("$root"/varde-*)
fi
python3 - "$root" "${skills[@]}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
bad = []
paths = []
for skill in sys.argv[2:]:
    base = Path(skill)
    paths.extend([base / 'SKILL.md', *sorted((base / 'references').glob('*.md'))])
for path in paths:
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
