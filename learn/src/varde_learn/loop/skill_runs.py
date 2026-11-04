"""Pure per-session skill runs, how-topic loads and post-run failures."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .diagnose.metrics import (
    _family,
    _is_tool_call,
    _is_tool_error,
    paired_records,
    value,
)
from .diagnose.model import EvidenceRecord

ERROR_WINDOW_CALLS = 10
FIRST_ERROR_BYTES = 200
READ_TOOLS = {"read", "cat", "sed", "head"}
SHELLS = {"bash", "sh", "zsh"}
SKILL_PATH = re.compile(r"(?:^|/)(varde-[a-z-]+)/SKILL\.md$")


@dataclass(frozen=True)
class _Call:
    index: int
    name: str
    command: list[str]
    failed: bool
    error: str | None
    excerpt: str = ""


def skill_runs(
    records: Iterable[EvidenceRecord | dict[str, Any]],
    signal_anchors: Sequence[int] = (),
) -> dict[str, dict[str, Any]]:
    """Map each skill that ran to its loads, post-run errors and skip suspicion.

    Anchors are waste-signal row indexes from the same record list.
    """
    calls = _calls(paired_records(list(records)))
    runs = [(position, _run_skill(call)) for position, call in enumerate(calls)]
    first_runs: dict[str, int] = {}
    for position, skill in runs:
        if skill:
            first_runs.setdefault(skill, position)
    loads = _loads(calls)
    result = {}
    for skill, position in first_runs.items():
        window = _window(calls, runs, position, skill)
        errors = [call for call in window if call.failed]
        in_window = any(
            window and calls[position].index < anchor <= window[-1].index
            for anchor in signal_anchors
        )
        skill_loads = sorted(loads.get(skill, ()))
        result[skill] = {
            "loads": skill_loads,
            "post_errors": len(errors),
            "first_error": _first_error(errors),
            "suspected_skip": not skill_loads and (bool(errors) or in_window),
        }
    return result


def _calls(rows: list[Any]) -> list[_Call]:
    failed_ids = _failed_ids(rows)
    calls: list[_Call] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if _is_tool_call(row):
            tool_id = _id(value(row, "tool_use_id"))
            seen.update(filter(None, [tool_id]))
            error = _row_error(row, failed_ids.get(tool_id or ""))
            name = str(value(row, "tool_name") or "")
            excerpt = str(value(row, "tool_input_excerpt") or "")
            calls.append(
                _Call(
                    index,
                    name,
                    _parse_command(excerpt),
                    _is_tool_error(row) or tool_id in failed_ids,
                    error,
                    excerpt,
                )
            )
            own = (name, excerpt)
        else:
            own = None
        for observation in value(row, "tool_observations") or []:
            call = _observation_call(index, observation, failed_ids, seen, own)
            if call:
                calls.append(call)
    return calls


def _id(raw: Any) -> str | None:
    return str(raw) if raw else None


def _failed_ids(rows: list[Any]) -> dict[str, str | None]:
    failed: dict[str, str | None] = {}
    for row in rows:
        for observation in value(row, "tool_observations") or []:
            tool_id = _id(value(observation, "tool_use_id"))
            error = value(observation, "error")
            status = str(value(observation, "status") or "").lower()
            failed_status = status in {"error", "failed", "failure"}
            is_result = value(observation, "block_type") == "tool_result"
            if tool_id and (error or failed_status) and (is_result or error):
                failed[tool_id] = error or value(observation, "output_excerpt")
    return failed


def _row_error(row: Any, observed: str | None) -> str | None:
    return value(row, "tool_error") or observed


def _observation_call(
    index: int,
    observation: Any,
    failed_ids: dict[str, str | None],
    seen: set[str],
    own: tuple[str, str] | None,
) -> _Call | None:
    name = value(observation, "tool_name")
    if not name or value(observation, "block_type") == "tool_result":
        return None
    tool_id = _id(value(observation, "tool_use_id"))
    if tool_id and tool_id in seen:
        return None
    if tool_id:
        seen.add(tool_id)
    excerpt = str(value(observation, "input_excerpt") or "")
    if not tool_id and own == (str(name), excerpt):
        return None
    error = value(observation, "error") or failed_ids.get(tool_id or "")
    failed = _is_tool_error(
        {"tool_status": value(observation, "status"), "tool_error": error}
    )
    return _Call(
        index,
        str(name),
        _parse_command(excerpt),
        failed or tool_id in failed_ids,
        error,
        excerpt,
    )


def _parse_command(excerpt: str) -> list[str]:
    """Split a tool input excerpt into tokens; JSON list values stay as tokens."""
    try:
        parsed = json.loads(excerpt)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        return _split(excerpt)
    tokens: list[str] = []
    for item in parsed.values():
        if isinstance(item, (str, int)):
            tokens.extend(_split(str(item)))
        elif isinstance(item, list):
            tokens.extend(str(part) for part in item if isinstance(part, (str, int)))
    return tokens


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _unwrap_shell(tokens: list[str]) -> list[str]:
    """Drop a leading `bash -lc`-style wrapper and split its script."""
    if _family(tokens) not in SHELLS:
        return tokens
    for position, token in enumerate(tokens[1:], start=1):
        if token.startswith("-") and "c" in token[1:]:
            return _flatten(tokens[position + 1 :])
    return tokens


def _run_skill(call: _Call) -> str | None:
    tool = call.name.lower()
    if tool == "skill":
        return _skill_tool_name(call)
    command = _unwrap_shell(_flatten(call.command))
    if tool not in READ_TOOLS and _family(command) not in READ_TOOLS:
        return None
    if "-i" in command or "--in-place" in command:
        return None
    for part in command:
        match = SKILL_PATH.search(part)
        if match:
            return match.group(1)
    return None


def _skill_tool_name(call: _Call) -> str | None:
    try:
        parsed = json.loads(call.excerpt)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        name = parsed.get("skill")
        return name.rsplit(":", 1)[-1] if isinstance(name, str) and name else None
    if not call.command:
        return None
    return call.command[0].rsplit(":", 1)[-1]


def _flatten(command: list[str]) -> list[str]:
    tokens: list[str] = []
    for token in command:
        if not any(char.isspace() for char in token):
            tokens.append(token)
            continue
        try:
            tokens.extend(shlex.split(token))
        except ValueError:
            tokens.extend(token.split())
    return tokens


def _load_of(command: list[str]) -> tuple[str, str] | None:
    tokens = _flatten(command)
    for position, token in enumerate(tokens):
        if _family([token]) != "varde" or tokens[position + 1 : position + 3] not in (
            ["doc", "how"],
            ["learn", "how"],
        ):
            continue
        operands = [
            item for item in tokens[position + 3 :] if not item.startswith("-")
        ][:2]
        if len(operands) == 2:
            return operands[0], operands[1]
    return None


def _loads(calls: list[_Call]) -> dict[str, set[str]]:
    loads: dict[str, set[str]] = {}
    for call in calls:
        found = _load_of(call.command)
        if found:
            loads.setdefault(found[0], set()).add(found[1])
    return loads


def _window(
    calls: list[_Call],
    runs: list[tuple[int, str | None]],
    position: int,
    skill: str,
) -> list[_Call]:
    window = []
    for later, other in runs[position + 1 : position + 1 + ERROR_WINDOW_CALLS]:
        if other and other != skill:
            break
        window.append(calls[later])
    return window


def _first_error(errors: list[_Call]) -> str | None:
    if not errors:
        return None
    text = errors[0].error
    if not text:
        return None
    return str(text).encode("utf-8")[:FIRST_ERROR_BYTES].decode("utf-8", "ignore")
