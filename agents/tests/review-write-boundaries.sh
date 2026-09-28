#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys
import json

root = pathlib.Path(sys.argv[1])
claude = (root / "review/claude.md").read_text()
codex = (root / "review/codex.toml").read_text()
opencode = (root / "review/opencode.md").read_text()
assert "Write" in claude and "Edit" not in claude and "Task" not in claude
# V2 has one edit action for both new artifacts and patches. The artifact-only
# boundary remains in the prompt; broad shell access is not a hard sandbox.
header = opencode.split("---", 2)[1]
rules = json.loads(next(line.removeprefix("permissions: ") for line in header.splitlines() if line.startswith("permissions: ")))
assert {r["action"]: r["effect"] for r in rules}["edit"] == "allow"
assert {r["action"]: r["effect"] for r in rules}["subagent"] == "deny"
assert 'sandbox_mode = "workspace-write"' in codex
for text in (claude, codex, opencode):
    lowered = " ".join(text.lower().split())
    assert "active review folder" in lowered
    assert "never edit production source" in lowered
    assert "write only review artifacts" in lowered
    for required in ("caller-assigned", "review-gates", "varde-workflow review inspect", "varde-workflow review record", "--expected-version", "do not", "baseline", "plan/task status"):
        assert required in lowered, required
    assert "approval boolean" in lowered
    assert "sole additional write" in lowered
print("Review write-boundary contract passed.")
PY
