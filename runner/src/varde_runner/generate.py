"""Read-only drift report for runner role configuration."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from varde_runner.config import config_path, load_config

CAPABILITY_HARNESS = {
    "codex-app-server": "codex",
    "pi": "pi",
    "claude-sdk": "claude",
}


def _differences(label: str, current: dict, expected: dict) -> list[str]:
    changes = [
        f"{field} {current.get(field)!r} -> {value!r}"
        for field, value in expected.items()
        if current.get(field) != value
    ]
    return [f"{label}: {', '.join(changes)}"] if changes else []


def check_drift(
    source: Path | None = None,
    agent_files: list[Path] | None = None,
    capabilities: Path | None = None,
) -> str:
    canonical_path = source or config_path()
    config = load_config(canonical_path)
    files = (
        agent_files
        if agent_files is not None
        else sorted((Path.home() / ".codex" / "agents").glob("*.toml"))
    )
    lines: list[str] = []
    for path in files:
        role_name = path.stem.removeprefix("varde-")
        role = config.roles.get(role_name)
        if role is None:
            continue
        try:
            old = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, tomllib.TOMLDecodeError:
            lines.append(f"{path}: cannot parse existing file")
            continue
        current = {
            "model": old.get("model"),
            "reasoning_effort": old.get(
                "model_reasoning_effort", old.get("reasoning_effort")
            ),
            "mode": old.get("sandbox_mode", old.get("mode")),
        }
        expected = {
            "model": role.model,
            "reasoning_effort": role.reasoning_effort,
            "mode": role.mode,
        }
        lines.extend(_differences(str(path), current, expected))
    capability_path = (
        capabilities
        or Path(__file__).parents[3]
        / "workflow"
        / "src"
        / "varde_workflow"
        / "agents"
        / "capabilities.json"
    )
    try:
        payload = json.loads(capability_path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return "\n".join(lines + [f"{capability_path}: unavailable"])
    for profile in payload.get("profiles", []):
        role = config.roles.get(profile.get("name", "").removeprefix("varde-"))
        if role is None:
            continue
        harness = CAPABILITY_HARNESS.get(role.harness)
        models = profile.get("models", {})
        branch = models.get(harness, {}) if isinstance(models, dict) else {}
        current = {
            "model": branch.get("model"),
            "reasoning_effort": branch.get("reasoning_effort"),
            "mode": branch.get("sandbox_mode", branch.get("mode")),
        }
        expected = {
            "model": role.model,
            "reasoning_effort": role.reasoning_effort,
            "mode": role.mode,
        }
        lines.extend(
            _differences(
                f"capabilities.json:{profile['name']}:{harness}", current, expected
            )
        )
    return "\n".join(lines) if lines else "No role model drift detected."


def main() -> int:
    print(check_drift())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
