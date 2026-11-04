#!/usr/bin/env bash
set -euo pipefail
: "${EVAL_SANDBOX_DIR:?EVAL_SANDBOX_DIR is required}"
: "${EVAL_RUN_DIR:?EVAL_RUN_DIR is required}"
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ['EVAL_SANDBOX_DIR'])
files = {
    str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in root.rglob('*.md') if p.is_file() and not p.is_symlink()
}
(Path(os.environ['EVAL_RUN_DIR']) / 'markdown-before.json').write_text(json.dumps(files))
PY
