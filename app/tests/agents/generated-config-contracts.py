#!/usr/bin/env python3
"""Check generated agent adapter values against the capability manifest."""

import importlib.util
import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS = REPO_ROOT / "workflow/src/varde_workflow/agents"
spec = importlib.util.spec_from_file_location(
    "agent_generator", REPO_ROOT / "app/scripts/generate.py"
)
assert spec is not None and spec.loader is not None
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
manifest = generator.load_manifest(AGENTS / "capabilities.json")


def frontmatter(path: Path) -> str:
    return path.read_text().split("---", 2)[1]


def v1_permissions(header: str) -> dict:
    line = next(line for line in header.splitlines() if line.startswith("permission: "))
    return json.loads(line.removeprefix("permission: "))


def v2_permissions(header: str) -> list[dict]:
    line = next(
        line for line in header.splitlines() if line.startswith("permissions: ")
    )
    return json.loads(line.removeprefix("permissions: "))


def yaml_value(header: str, key: str) -> str:
    line = next(line for line in header.splitlines() if line.startswith(f"{key}:"))
    value = line.split(":", 1)[1].strip()
    return json.loads(value) if value.startswith('"') else value


expected = {
    "varde-explorer": {
        "codex_model": "gpt-6-luna",
        "codex_effort": "medium",
        "sandbox": "read-only",
        "opencode_model": "deepseek/deepseek-v4-flash",
        "claude_model": "haiku",
        "opencode_edit": "deny",
    },
    "varde-builder": {
        "codex_model": "gpt-6-luna",
        "codex_effort": "medium",
        "sandbox": "workspace-write",
        "opencode_model": "deepseek/deepseek-v4-flash",
        "claude_model": "sonnet",
        "opencode_edit": "allow",
    },
}

for name, contract in expected.items():
    directory = AGENTS / name
    codex = tomllib.loads((directory / "codex.toml").read_text())
    assert codex["model"] == contract["codex_model"], f"{name}: Codex model"
    assert codex["model_reasoning_effort"] == contract["codex_effort"], (
        f"{name}: Codex effort"
    )
    assert codex.get("sandbox_mode") == contract["sandbox"], f"{name}: sandbox mode"

    opencode_v1 = frontmatter(directory / "opencode.md")
    opencode_v2 = frontmatter(directory / "opencode-v2.md")
    permission_v1 = v1_permissions(opencode_v1)
    permission_v2 = v2_permissions(opencode_v2)
    assert permission_v1["edit"] == contract["opencode_edit"], (
        f"{name}: OpenCode v1 edit"
    )
    assert any(
        item["action"] == "edit" and item["effect"] == contract["opencode_edit"]
        for item in permission_v2
    ), name
    assert yaml_value(opencode_v1, "model") == contract["opencode_model"], (
        f"{name}: OpenCode v1 model"
    )
    assert yaml_value(opencode_v2, "model") == contract["opencode_model"], (
        f"{name}: OpenCode v2 model"
    )
    assert yaml_value(opencode_v1, "mode") == "subagent", f"{name}: OpenCode v1 mode"
    assert yaml_value(opencode_v2, "mode") == "subagent", f"{name}: OpenCode v2 mode"

    claude = frontmatter(directory / "claude.md")
    assert yaml_value(claude, "model") == contract["claude_model"], (
        f"{name}: Claude model"
    )

builder_text = "\n".join(
    path.read_text() for path in (AGENTS / "varde-builder").iterdir() if path.is_file()
)
assert "skill workflow, not a shell command" in builder_text
assert "varde change" not in builder_text, "builder text suggests a nonexistent CLI"

for profile in manifest["profiles"]:
    name = profile["name"]
    for filename in ("opencode.md", "opencode-v2.md"):
        assert (
            yaml_value(frontmatter(AGENTS / name / filename), "mode") == "subagent"
        ), f"{name}: {filename} mode"

print("Generated agent configuration contracts passed.")
