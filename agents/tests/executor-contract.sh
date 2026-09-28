#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
claude = (root / "executor/claude.md").read_text()
codex = (root / "executor/codex.toml").read_text()
opencode = (root / "executor/opencode.md").read_text()
for text in (claude, codex, opencode):
    lowered = " ".join(text.lower().split())
    for required in (
        "exactly one bounded implementation task", "location", "ownership", "checks", "constraints",
        "varde-workflow", "plan-wide state", "verification", "commits", "blockers",
        "report observed session-friction evidence to the orchestrator", "orchestrator owns capture",
        "do not write", "promote session observations to stored friction",
        "does not restrict writes required by the assigned task",
    ):
        assert required in lowered, required
    assert "do not plan" in lowered
    assert "do not" in lowered and ("spawn" in lowered or "delegate" in lowered)
    assert "varde-change build" in lowered
    for required in ("caller-supplied review subject", "varde-workflow review check", "--checkpoint", "start", "resume", "never author your own approval", "prose or a boolean", "workflow cli is unavailable"):
        assert required in lowered, required
assert "Task" not in claude.split("\n", 8)[4]
assert "task:" not in opencode.split("---", 2)[1]
assert "sandbox_mode = \"workspace-write\"" in codex
print("Executor contract passed.")
PY
