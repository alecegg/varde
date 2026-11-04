from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.loop.codex import parse_codex


def _trace(completion: dict | None, *, target: str = "/repo/skill/SKILL.md") -> bytes:
    events = [
        {"type": "thread.started", "thread_id": "thread"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "cmd",
                "type": "command_execution",
                "command": f"cat {target}",
                "status": "in_progress",
            },
        },
    ]
    if completion is not None:
        events.append({"type": "item.completed", "item": completion})
    events.append({"type": "turn.completed"})
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode()


def test_completed_command_after_start_counts_as_hit(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    completed = {
        "id": "cmd",
        "type": "command_execution",
        "command": f"cat {skill / 'SKILL.md'}",
        "status": "completed",
        "exit_code": 0,
    }
    assert parse_codex(_trace(completed, target=str(skill / "SKILL.md")), skill)


def test_started_command_without_completion_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unusable Codex trace"):
        parse_codex(_trace(None), tmp_path / "skill")


def test_completed_command_requires_status_and_exit_code(tmp_path: Path) -> None:
    completion = {
        "id": "cmd",
        "type": "command_execution",
        "command": "cat /repo/skill/SKILL.md",
    }
    with pytest.raises(ValueError, match="unusable Codex trace"):
        parse_codex(_trace(completion), tmp_path / "skill")
