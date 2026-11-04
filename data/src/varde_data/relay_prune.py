"""Prune old runner mailman generations from the relay state cache."""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.locking import atomic_write, file_lock
from varde_data.views.relay_liveness import RUNNER_WAITING_STALE_SECONDS

KEEP_PREVIOUS_GENERATIONS = 5


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.timestamp()


def _generation_order(state: dict[str, Any], tokens: list[str]) -> list[str]:
    started = state.get("mailman_started")
    started = started if isinstance(started, dict) else {}
    latest_events: dict[str, int] = {}
    events = state.get("events")
    if isinstance(events, list):
        for index, event in enumerate(events):
            if isinstance(event, dict) and isinstance(event.get("token_id"), str):
                latest_events[event["token_id"]] = index
    insertion_order = {token: index for index, token in enumerate(tokens)}

    def order(token: str) -> tuple[float, int, int]:
        started_at = _timestamp(started.get(token))
        return (
            started_at if started_at is not None else float("-inf"),
            latest_events.get(token, -1),
            insertion_order[token],
        )

    return sorted(tokens, key=order)


def _recent_waiting_tokens(state: dict[str, Any], now: datetime) -> set[str]:
    events = state.get("events")
    latest: dict[str, dict[str, Any]] = {}
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and isinstance(event.get("token_id"), str):
                latest[event["token_id"]] = event
    protected = set()
    for token, event in latest.items():
        at = _timestamp(event.get("at"))
        if (
            event.get("event") == "waiting"
            and at is not None
            and now.astimezone(UTC) - datetime.fromtimestamp(at, UTC)
            <= timedelta(seconds=RUNNER_WAITING_STALE_SECONDS)
        ):
            protected.add(token)
    return protected


def _bound_tokens(root: Path) -> set[str]:
    inbox = root.parent
    protected = set()
    for pointer in (inbox / "addresses").glob("*/current"):
        try:
            binding = json.loads(pointer.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if isinstance(binding, dict) and isinstance(binding.get("token_id"), str):
            protected.add(binding["token_id"])
    return protected


def _action_ids(state: dict[str, Any]) -> tuple[set[str], set[str]]:
    action_ids: set[str] = set()
    protected: set[str] = set()
    leases = state.get("leases")
    if isinstance(leases, list):
        for row in leases:
            if isinstance(row, dict):
                token = row.get("token_id")
                action_id = row.get("action_id")
                if isinstance(token, str):
                    protected.add(token)
                if isinstance(action_id, str):
                    action_ids.add(action_id)
    attempts = state.get("attempts")
    if isinstance(attempts, dict):
        for rows in attempts.values():
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        token = row.get("token_id")
                        action_id = row.get("action_id")
                        if isinstance(token, str):
                            protected.add(token)
                        if isinstance(action_id, str):
                            action_ids.add(action_id)
    return protected, action_ids


def _action_tokens(root: Path, action_ids: set[str]) -> set[str]:
    protected = set()
    for action_id in action_ids:
        try:
            action = json.loads(
                (root / "actions" / f"{action_id}.json").read_text(encoding="utf-8")
            )
        except OSError, ValueError:
            continue
        if isinstance(action, dict) and isinstance(action.get("token_id"), str):
            protected.add(action["token_id"])
    return protected


def _referenced_tokens(state: dict[str, Any], root: Path, now: datetime) -> set[str]:
    action_tokens, action_ids = _action_ids(state)
    return (
        _recent_waiting_tokens(state, now)
        | _bound_tokens(root)
        | action_tokens
        | _action_tokens(root, action_ids)
    )


def _pruned_state(
    state: dict[str, Any], protected: set[str]
) -> tuple[dict[str, Any], int, int]:
    maps = {
        name: value
        for name in ("mailman_started", "mailman_instances", "cycles")
        if isinstance((value := state.get(name)), dict)
    }
    tokens = list(
        dict.fromkeys(str(token) for mapping in maps.values() for token in mapping)
    )
    current = state.get("current_mailman")
    keep = {current} if isinstance(current, str) and current else set()
    keep.update(protected)
    recent = [token for token in _generation_order(state, tokens) if token not in keep]
    keep.update(recent[-KEEP_PREVIOUS_GENERATIONS:])
    pruned = len(tokens) - len(keep.intersection(tokens))
    result = dict(state)
    for name, mapping in maps.items():
        filtered = {key: value for key, value in mapping.items() if str(key) in keep}
        result[name] = filtered
    return result, pruned, len(keep.intersection(tokens))


def prune_legacy_mailman_state(
    working: Path, *, now: datetime | None = None
) -> dict[str, Any]:
    """Keep current plus five previous mailman generations, backing up first."""
    if os.environ.get("VARDE_RELAY_PRUNE", "1") == "0":
        return {"disabled": True, "pruned": 0, "kept": 0}
    root = working.expanduser().resolve() / ".cache" / "inbox" / "relay"
    path = root / "state.json"
    if not path.is_file():
        return {"disabled": False, "pruned": 0, "kept": 0}

    with file_lock(root / ".lock", timeout=30):
        original = path.read_bytes()
        state = json.loads(original)
        if not isinstance(state, dict):
            return {"disabled": False, "pruned": 0, "kept": 0}
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        protected = _referenced_tokens(state, root, moment)
        pruned_state, pruned, kept = _pruned_state(state, protected)
        if not pruned:
            return {"disabled": False, "pruned": 0, "kept": kept}
        suffix = moment.strftime("%Y%m%dT%H%M%S.%fZ")
        shutil.copy2(path, path.with_name(f"state.json.bak-{suffix}"))
        mode = stat.S_IMODE(path.stat().st_mode)
        serialized = json.dumps(pruned_state, ensure_ascii=False, indent=2) + "\n"
        atomic_write(path, serialized.encode("utf-8"), mode=mode)
    return {"disabled": False, "pruned": pruned, "kept": kept}
