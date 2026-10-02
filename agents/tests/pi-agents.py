#!/usr/bin/env python3
"""Check the generated Pi (@tintinweb/pi-subagents) agent definitions."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

AGENTS = pathlib.Path(__file__).resolve().parent.parent
PROFILES = ("varde-executor", "varde-explorer", "varde-planner", "varde-reviewer")
BUILTIN_TOOLS = {"read", "bash", "edit", "write", "grep", "find", "ls"}
SPAWNERS = {"varde-executor", "varde-planner", "varde-reviewer"}
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
    assert "write" in tools["varde-executor"] and "edit" in tools["varde-executor"]
    assert "edit" not in tools["varde-reviewer"], "the reviewer never edits source"

    # Installer: PI_CODING_AGENT_DIR wins, files are <name>.md, models are preserved.
    with tempfile.TemporaryDirectory() as temporary:
        env = {**os.environ, "PI_CODING_AGENT_DIR": temporary, "HOME": temporary + "/home"}
        run = lambda *args: subprocess.run(
            [str(AGENTS / "install.sh"), "-t", "pi", *args],
            env=env, check=True, capture_output=True, text=True,
        ).stdout
        run("-f")
        for profile in PROFILES:
            assert (pathlib.Path(temporary) / "agents" / f"{profile}.md").is_file(), profile
        installed = pathlib.Path(temporary) / "agents" / "varde-planner.md"
        assert "model:" not in installed.read_text()
        installed.write_text(installed.read_text().replace(
            "tools:", 'model: "anthropic/claude-sonnet-4-5"\ntools:', 1))
        out = run("-m")
        assert "Preserved user model setting model" in out, out
        assert 'model: "anthropic/claude-sonnet-4-5"' in installed.read_text()
        default_env = {**env}
        del default_env["PI_CODING_AGENT_DIR"]
        out = subprocess.run(
            [str(AGENTS / "install.sh"), "-t", "pi", "-n"],
            env=default_env, check=True, capture_output=True, text=True,
        ).stdout
        assert f"{temporary}/home/.pi/agent/agents" in out, out
    print("Pi agent assertions passed.")


if __name__ == "__main__":
    sys.exit(main())
