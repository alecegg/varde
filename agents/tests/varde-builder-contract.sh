#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
claude = (root / "varde-builder/claude.md").read_text()
codex = (root / "varde-builder/codex.toml").read_text()
opencode = (root / "varde-builder/opencode.md").read_text()
opencode_v2 = (root / "varde-builder/opencode-v2.md").read_text()
for text in (claude, codex, opencode, opencode_v2):
    lowered = " ".join(text.lower().split())
    for required in (
        "exactly one bounded implementation task", "location", "ownership", "checks", "constraints",
        "plan-wide state", "verification", "commits", "blockers",
        "report observed session-friction evidence to the caller", "caller owns capture",
        "do not write", "promote session observations to stored friction",
        "does not restrict writes required by the assigned task",
    ):
        assert required in lowered, required
    assert "do not plan" in lowered
    assert "spawn nothing except `varde-explorer`, and only as many as your brief allows" in lowered
    assert "do the task yourself" in lowered
    assert "varde-agent-doc-authoring" in lowered
    assert "varde-change build" in lowered
    assert "varde-review fix" in lowered
    assert "loaded `varde-review` skill" in lowered
    # Review-subject, binding and checkpoint text is cut (B-agent-1, B-gate-5).
    for removed in (
        "caller-supplied review subject", "checkpoint", "never author your own approval",
        "prose or a boolean", "workflow cli is unavailable", "mode=build", "plan_context",
        "finding_ids", "triage findings",
    ):
        assert removed not in lowered, removed
assert "Task" not in claude.split("\n", 8)[4]
# V1 grants only varde-explorer in its task map; V2 grants only that subagent resource.
assert '"task": {"*": "deny", "varde-explorer": "allow"}' in opencode.split("---", 2)[1]
assert '{"action": "subagent", "resource": "varde-explorer", "effect": "allow"}' in opencode_v2.split("---", 2)[1]
assert "sandbox_mode = \"workspace-write\"" in codex
print("Builder contract passed.")
PY
