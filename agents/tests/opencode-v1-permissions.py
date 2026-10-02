#!/usr/bin/env python3
"""Check V1 OpenCode permission maps against the profile contracts (no model calls)."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "capabilities.json").read_text())
expected_edit = {"varde-planner": "allow", "varde-executor": "allow", "varde-reviewer": "allow", "varde-explorer": "deny"}


def effect(allowed: bool) -> str:
    return "allow" if allowed else "deny"


for profile in manifest["profiles"]:
    name = profile["name"]
    tools = set(profile["opencode_tools"])
    header = (root / name / "opencode.md").read_text().split("---", 2)[1]
    assert "\ntools:" not in header and "\npermissions:" not in header, name
    line = next(line for line in header.splitlines() if line.startswith("permission: "))
    permission = json.loads(line.removeprefix("permission: "))
    assert isinstance(permission, dict), name
    assert permission == {
        "read": effect("read" in tools), "glob": effect("glob" in tools),
        "grep": effect("grep" in tools), "bash": effect("bash" in tools),
        "edit": effect(bool(tools & {"write", "edit"})),
        "skill": "allow",
        "task": {"*": "deny", "varde-explorer": "allow"} if profile["spawns"] else "deny",
    }, name
    assert profile["spawns"] == ([] if name == "varde-explorer" else ["varde-explorer"]), name
    assert permission["edit"] == expected_edit[name], name
    assert "mode: subagent" in header, name
print("OpenCode V1 permission contracts passed.")
