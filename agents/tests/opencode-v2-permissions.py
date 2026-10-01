#!/usr/bin/env python3
"""Check V2 capabilities against the agreed profile contracts (no model calls)."""
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

root = Path(__file__).resolve().parents[1]
expected_edit = {"varde-planner": "allow", "varde-executor": "allow", "varde-reviewer": "allow", "varde-explorer": "deny"}
for name, edit in expected_edit.items():
    header = (root / name / "opencode.md").read_text().split("---", 2)[1]
    assert "\ntools:" not in header and "\npermission:" not in header, name
    line = next(line for line in header.splitlines() if line.startswith("permissions: "))
    rules = json.loads(line.removeprefix("permissions: "))
    assert all(set(rule) == {"action", "resource", "effect"} for rule in rules), name
    assert len({rule["action"] for rule in rules}) == len(rules), name
    assert {rule["action"]: rule["effect"] for rule in rules} == {
        "read": "allow", "glob": "allow", "grep": "allow", "shell": "allow",
        "edit": edit, "skill": "allow", "subagent": "deny",
    }, name
    assert all(rule["resource"] == "*" for rule in rules), name
    assert "mode: subagent" in header, name

spec = importlib.util.spec_from_file_location("generate", root / "generate.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
manifest = json.loads((root / "capabilities.json").read_text())
manifest["profiles"][0]["opencode_tools"].append("unknown-tool")
try:
    generator.validate_profiles(manifest, manifest["skills"], manifest["profiles"])
except ValueError:
    pass
else:
    raise AssertionError("Unknown legacy capabilities must not silently broaden permissions")
print("OpenCode V2 permission contracts passed.")
