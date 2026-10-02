#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
claude = (root / "varde-executor/claude.md").read_text()
codex = (root / "varde-executor/codex.toml").read_text()
opencode = (root / "varde-executor/opencode.md").read_text()
opencode_v2 = (root / "varde-executor/opencode-v2.md").read_text()
for text in (claude, codex, opencode, opencode_v2):
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
    assert "spawn only `varde-explorer` (up to 2 at a time), and only if you have a spawn tool" in lowered
    assert "without spawning or delegating" not in lowered
    assert "varde-change build" in lowered
    for required in ("caller-supplied review subject", "varde-workflow review check", "--checkpoint", "start", "resume", "never author your own approval", "prose or a boolean", "workflow cli is unavailable"):
        assert required in lowered, required
assert "Task" not in claude.split("\n", 8)[4]
# V1 grants only varde-explorer in its task map; V2 grants only that subagent resource.
assert '"task": {"*": "deny", "varde-explorer": "allow"}' in opencode.split("---", 2)[1]
assert '{"action": "subagent", "resource": "varde-explorer", "effect": "allow"}' in opencode_v2.split("---", 2)[1]
assert "sandbox_mode = \"workspace-write\"" in codex
print("Executor contract passed.")
PY
