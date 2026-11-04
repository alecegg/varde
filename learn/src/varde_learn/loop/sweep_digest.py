"""Rank sweep findings and optionally summarize them with the Claude CLI."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from varde_data.ledger import open_ledger


def _estimated_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def rank_candidates(
    findings: list[dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    """Sort candidates by estimated time saved, then tokens saved."""
    return sorted(
        findings,
        key=lambda item: (
            -float(item.get("estimated_seconds_saved", 0)),
            -int(item.get("estimated_tokens_saved", 0)),
            str(item.get("title", "")),
        ),
    )[:limit]


def render_digest(ranked: list[dict[str, Any]]) -> str:
    """Render ranked findings as a compact plain-text digest."""
    if not ranked:
        return "No improvement candidates found."
    return "\n".join(
        f"{index}. {item['title']} (about {item.get('estimated_seconds_saved', 0)}s / "
        f"{item.get('estimated_tokens_saved', 0)} tokens saved)"
        for index, item in enumerate(ranked, 1)
    )


def summarize_with_claude(
    digest: str, *, token_cap: int, input_tokens: int | None = None
) -> tuple[str | None, int | None]:
    """Use Claude CLI within a hard combined input/output token budget."""
    prompt = (
        f"Summarize these improvement candidates in three concise bullets:\n{digest}"
    )
    estimated_input = (
        input_tokens if input_tokens is not None else _estimated_tokens(prompt)
    )
    if estimated_input >= token_cap or shutil.which("claude") is None:
        return None, None
    max_output = token_cap - estimated_input
    completed = subprocess.run(
        [  # noqa: S607 - resolve this optional CLI through PATH.
            "claude",
            "-p",
            "--model",
            "haiku",
            "--tools",
            "",
            "--output-format",
            "json",
        ],
        input=prompt,
        env={**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_output)},
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    if completed.returncode:
        return None, None
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, None
    text = response.get("result") if isinstance(response, dict) else None
    usage = response.get("usage", {}) if isinstance(response, dict) else {}
    output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
    actual_input = usage.get("input_tokens") if isinstance(usage, dict) else None
    measured_input = actual_input if isinstance(actual_input, int) else estimated_input
    measured = (
        measured_input + output_tokens if isinstance(output_tokens, int) else None
    )
    if not isinstance(text, str) or measured is None or measured > token_cap:
        return None, measured
    return text.strip(), measured


def write_digest(
    store: Path,
    run_date: date,
    digest: str,
    candidates: list[dict[str, Any]],
) -> Path:
    open_ledger(store).write_digest(run_date, digest, candidates)
    return store / "digests" / f"{run_date.isoformat()}.json"


def read_digest(store: Path, run_date: date) -> dict[str, Any] | None:
    value = open_ledger(store).read_digest(run_date)
    return None if value is None else asdict(value)


def summary_config() -> tuple[bool, int]:
    config = Path.home() / ".config/varde/learn/sweep.toml"
    if not config.exists():
        return False, 2000
    import tomllib

    value = tomllib.loads(config.read_text(encoding="utf-8"))
    settings = value.get("summary", {})
    if not isinstance(settings, dict):
        raise TypeError("sweep summary config must be a table")
    enabled = settings.get("enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("sweep summary enabled must be true or false")
    cap = settings.get("token_cap", 2000)
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("sweep summary token_cap must be a positive integer")
    return enabled, cap
