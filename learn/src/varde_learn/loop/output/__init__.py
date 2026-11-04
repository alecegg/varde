"""Output eval run primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Config(str, Enum):
    WITH_SKILL = "with_skill"
    WITHOUT_SKILL = "without_skill"


class EvalOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class OutputHarness(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"


@dataclass
class RunRecord:
    eval_id: str
    config: Config
    run: int
    run_dir: Path
    outcome: EvalOutcome
    judge_outcome: str
    total_assertions: int
    passed_assertions: int
    pass_rate: float | None
    duration_ms: int
    measured_tokens: int | None
    cost_usd: float | None
    blocked: bool
    assertions: list[str]
    cost: Any
    redacted: int = 0


def extract_transcript(value: dict[str, Any]) -> str:
    if isinstance(value.get("result"), str):
        return value["result"]
    return "\n".join(
        part["text"]
        for message in value.get("messages", [])
        if isinstance(message, dict)
        for part in message.get("content", [])
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    )


def extract_tokens(value: dict[str, Any]) -> tuple[bool, int]:
    usage = value.get("usage")
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    if not isinstance(usage, dict):
        return False, 0
    numbers = [
        usage[key]
        for key in fields
        if isinstance(usage.get(key), int)
        and not isinstance(usage[key], bool)
        and usage[key] >= 0
    ]
    return bool(numbers), sum(numbers)
