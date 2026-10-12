#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys
import json

root = pathlib.Path(sys.argv[1])
claude = (root / "varde-reviewer/claude.md").read_text()
codex = (root / "varde-reviewer/codex.toml").read_text()
opencode = (root / "varde-reviewer/opencode.md").read_text()
opencode_v2 = (root / "varde-reviewer/opencode-v2.md").read_text()
assert "Write" in claude and "Edit" not in claude and "Task" not in claude
# Both OpenCode generations have one edit action for new artifacts and patches.
# The artifact-only boundary remains in the prompt; broad shell access is not a
# hard sandbox. V1 uses a permission map, V2 a permissions list.
header = opencode.split("---", 2)[1]
permission = json.loads(next(line.removeprefix("permission: ") for line in header.splitlines() if line.startswith("permission: ")))
assert permission["edit"] == "allow"
assert permission["task"] == {"*": "deny", "varde-explorer": "allow"}
header = opencode_v2.split("---", 2)[1]
rules = json.loads(next(line.removeprefix("permissions: ") for line in header.splitlines() if line.startswith("permissions: ")))
assert {r["action"]: r["effect"] for r in rules}["edit"] == "allow"
assert [(r["resource"], r["effect"]) for r in rules if r["action"] == "subagent"] == [("*", "deny"), ("varde-explorer", "allow")]
assert 'sandbox_mode = "workspace-write"' in codex
for text in (claude, codex, opencode, opencode_v2):
    lowered = " ".join(text.lower().split())
    assert "active review folder" in lowered
    assert "never edit production source" in lowered
    assert "write only review artifacts" in lowered
    assert "do not change plan or task status" in lowered
    assert "spawn nothing except `varde-explorer`, and only as many as your brief allows" in lowered
    for removed in ("gate evidence", "sole additional write", "approval boolean", "varde plan review"):
        assert removed not in lowered, removed
print("Review write-boundary contract passed.")
PY
