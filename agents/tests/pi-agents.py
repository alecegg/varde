#!/usr/bin/env python3
"""Check the generated Pi (@tintinweb/pi-subagents) agent definitions."""
import json
import pathlib
import sys

AGENTS = pathlib.Path(__file__).resolve().parent.parent
PROFILES = ("varde-builder", "varde-explorer", "varde-planner", "varde-reviewer")
BUILTIN_TOOLS = {"read", "bash", "edit", "write", "grep", "find", "ls"}
SPAWNERS = {"varde-builder", "varde-planner", "varde-reviewer"}
AGENTS_LINE = "Read the repository's AGENTS.md, if present, before working."


def parse(text):
    """Return (fields, body); values are JSON-decoded when quoted."""
    assert text.startswith("---\n"), "missing frontmatter"
    header, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in header.splitlines():
        key, _, value = line.partition(": ")
        assert key not in fields, f"duplicate key {key}"
        fields[key] = json.loads(value) if value.startswith('"') else value
    return fields, body


def check_profile(profile):
    fields, body = parse((AGENTS / profile / "pi.md").read_text())
    assert fields["description"], profile
    tools = [t.strip() for t in fields["tools"].split(",")]
    assert set(tools) <= BUILTIN_TOOLS and len(tools) == len(set(tools)), (profile, tools)
    assert "read" in tools and "bash" in tools, (profile, tools)
    assert "model" not in fields, "Pi agents inherit the session model"
    assert fields["prompt_mode"] == "replace", profile
    assert fields["skills"] == "true", profile
    assert "name" not in fields, "the filename names a Pi agent"
    if profile in SPAWNERS:
        assert fields["allowed_subagents"] == "varde-explorer", profile
    else:
        assert "allowed_subagents" not in fields, profile
    assert set(fields) <= {
        "description", "tools", "model", "prompt_mode", "skills", "allowed_subagents",
    }, (profile, sorted(fields))
    assert body.count(AGENTS_LINE) == 1, profile
    claude_body = (AGENTS / profile / "claude.md").read_text().split("-->\n", 1)[1]
    assert claude_body.strip() in body, f"{profile} body omits the shared instructions"
    return tools


def main():
    tools = {profile: check_profile(profile) for profile in PROFILES}
    assert tools["varde-explorer"] == ["read", "bash", "grep", "find", "ls"], tools["varde-explorer"]
    assert not {"edit", "write"} & set(tools["varde-explorer"])
    assert "write" in tools["varde-builder"] and "edit" in tools["varde-builder"]
    assert "edit" not in tools["varde-reviewer"], "the reviewer never edits source"

    print("Pi agent assertions passed.")


if __name__ == "__main__":
    sys.exit(main())
