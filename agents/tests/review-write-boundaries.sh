#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
claude = (root / "review/claude.md").read_text()
codex = (root / "review/codex.toml").read_text()
opencode = (root / "review/opencode.md").read_text()
assert "Write" in claude and "Edit" not in claude and "Task" not in claude
assert "write: true" in opencode and "edit: false" in opencode and "task:" not in opencode
assert 'sandbox_mode = "workspace-write"' in codex
for text in (claude, codex, opencode):
    lowered = text.lower()
    assert "active review folder" in lowered
    assert "never edit production source" in lowered
    assert "write only review artifacts" in lowered
print("Review write-boundary contract passed.")
PY
