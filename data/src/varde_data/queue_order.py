"""Saved plan ordering: pure ordering rules and the locked order file."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

_ORDER_LOCK = threading.Lock()


class OrderMismatch(ValueError):
    """The ids to save are not exactly the ids that currently exist."""


def _raise(error: Exception) -> Never:
    raise error


def ordered_ids(plan_ids: list[str], saved_order: list[str]) -> list[str]:
    known = set(plan_ids)
    ordered = list(dict.fromkeys(item for item in saved_order if item in known))
    return ordered + sorted(known - set(ordered))


def move_plan(plan_ids: list[str], plan_id: str, direction: str) -> list[str]:
    if direction not in {"up", "down"}:
        raise ValueError("direction must be up or down")
    try:
        index = plan_ids.index(plan_id)
    except ValueError as exc:
        raise KeyError(plan_id) from exc
    target = index + (-1 if direction == "up" else 1)
    if target < 0 or target >= len(plan_ids):
        raise ValueError("plan is already at the category boundary")
    result = list(plan_ids)
    result[index], result[target] = result[target], result[index]
    return result


def full_order(current: list[str], requested: list[str]) -> list[str]:
    """Return `requested` when it is exactly a permutation of `current`."""
    if len(requested) != len(set(requested)) or set(requested) != set(current):
        raise OrderMismatch("ids must be exactly the current ids, each once")
    return list(requested)


def _string_list(value: Any) -> list[str]:
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def read_order(path: Path, categories: dict[str, list[str]]) -> dict[str, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("order"), dict)
        ):
            _raise(ValueError("invalid queue order"))
        stored = value["order"]
    except OSError, ValueError, TypeError:
        stored = {}
    return {
        category: ordered_ids(ids, _string_list(stored.get(category)))
        for category, ids in categories.items()
    }


def has_saved_order(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, TypeError:
        return False
    return (
        isinstance(value, dict)
        and value.get("version") == 1
        and isinstance(value.get("order"), dict)
    )


def _locked_update(
    path: Path,
    categories: dict[str, list[str]],
    category: str,
    update: Any,
) -> dict[str, list[str]]:
    lock_path = path.with_name(f".{path.name}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ORDER_LOCK, lock_path.open("a", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream, fcntl.LOCK_EX)
        try:
            stored = read_order(path, categories)
            stored[category] = update(
                ordered_ids(categories[category], stored[category])
            )
            _write_order_locked(path, stored)
            return stored
        finally:
            fcntl.flock(lock_stream, fcntl.LOCK_UN)


def move_order(
    path: Path,
    categories: dict[str, list[str]],
    category: str,
    plan_id: str,
    direction: str,
) -> dict[str, list[str]]:
    return _locked_update(
        path,
        categories,
        category,
        lambda current: move_plan(current, plan_id, direction),
    )


def set_order(
    path: Path,
    categories: dict[str, list[str]],
    category: str,
    requested: list[str],
) -> dict[str, list[str]]:
    """Save a full ordering of one category; raise OrderMismatch if the set differs."""
    return _locked_update(
        path,
        categories,
        category,
        lambda current: full_order(current, requested),
    )


def _write_order_locked(path: Path, order: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "version": 1,
            "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "order": order,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
