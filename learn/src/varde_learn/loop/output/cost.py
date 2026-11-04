"""Read usage and cost from captured harness traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def collect(harness: str, evaluated_trace: Path, judge_trace: Path) -> dict[str, Any]:
    evaluated, judge = (
        _read_usage(harness, evaluated_trace),
        _read_usage(harness, judge_trace),
    )
    return {
        "evaluated": evaluated["cost"]
        if evaluated["cost"] is not None
        else "unavailable",
        "judge": judge["cost"] if judge["cost"] is not None else "unavailable",
        "tokens": {
            key: item["tokens"] if item["tokens"] is not None else "unavailable"
            for key, item in (("evaluated", evaluated), ("judge", judge))
        },
    }


def _read_usage(path_harness: str, path: Path) -> dict[str, int | float | None]:
    try:
        text = path.read_text()
    except OSError:
        return {"cost": None, "tokens": None}
    if path_harness == "claude":
        try:
            events = [json.loads(text)]
        except ValueError, TypeError:
            events = []
    else:
        events = []
        for line in text.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    found: dict[str, int | float | None] = {"cost": None, "tokens": None}
    for event in events:
        if not isinstance(event, dict):
            continue
        usage = event.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        for value in (
            event.get("total_cost_usd"),
            event.get("cost_usd"),
            usage.get("total_cost_usd"),
            usage.get("cost_usd"),
        ):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                found["cost"] = value
                break
        total = usage.get("total_tokens")
        input_tokens, output_tokens = (
            usage.get("input_tokens"),
            usage.get("output_tokens", 0),
        )
        if isinstance(total, int) and total >= 0:
            found["tokens"] = total
        elif isinstance(input_tokens, int) and input_tokens >= 0:
            found["tokens"] = input_tokens + (
                output_tokens
                if isinstance(output_tokens, int) and output_tokens >= 0
                else 0
            )
        elif isinstance(usage.get("output_tokens"), int):
            found["tokens"] = usage["output_tokens"]
    return found
