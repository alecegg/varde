"""Harness IDs, layouts, detection, and selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..hooks_install import config_home


class HarnessId(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"
    PI = "pi"

    @classmethod
    def parse(cls, value: str) -> HarnessId:
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"unknown harness id: {value}") from exc


@dataclass(frozen=True)
class Harness:
    id: HarnessId
    skills_dir: Path | None
    agents_dir: Path


def _layout(identifier: HarnessId, home: Path, pi_agent_dir: Path | None) -> Harness:
    roots = {
        HarnessId.CLAUDE: (home / ".claude/skills", home / ".claude/agents"),
        HarnessId.CODEX: (home / ".codex/skills", home / ".codex/agents"),
        HarnessId.OPENCODE: (
            config_home(home) / "opencode/skills",
            config_home(home) / "opencode/agents",
        ),
        HarnessId.PI: (None, (pi_agent_dir or home / ".pi/agent") / "agents"),
    }
    skills, agents = roots[identifier]
    return Harness(identifier, skills, agents)


def detect(home: Path, pi_agent_dir: Path | None = None) -> list[Harness]:
    available = {
        HarnessId.CLAUDE: (home / ".claude").is_dir(),
        HarnessId.CODEX: (home / ".codex").is_dir(),
        HarnessId.OPENCODE: (config_home(home) / "opencode").is_dir(),
        HarnessId.PI: (home / ".pi").is_dir() or bool(pi_agent_dir),
    }
    return [
        _layout(identifier, home, pi_agent_dir)
        for identifier in HarnessId
        if available[identifier]
    ]


def select(
    ids: list[HarnessId], home: Path, pi_agent_dir: Path | None = None
) -> list[Harness]:
    return [
        _layout(identifier, home, pi_agent_dir)
        for identifier in HarnessId
        if identifier in ids
    ]
