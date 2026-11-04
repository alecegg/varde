"""Structured pipeline checkpoints, turn counters, and token accounting."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1
WORKER_TOKEN_LIMIT = 250_000
WORKER_TURN_LIMIT = 60
WORKER_HARD_STOP = 350_000
ORCHESTRATOR_TOKEN_LIMIT = 400_000

_REQUIRED_FIELDS = (
    "schema_version",
    "session_id",
    "harness",
    "role",
    "turn",
    "current_item",
    "worktree",
    "branch",
    "last_commit",
    "queue_position",
    "decisions_made",
    "pending_findings",
    "next_actions",
    "files_touched",
    "token_usage",
)
_LIST_FIELDS = ("decisions_made", "pending_findings", "next_actions", "files_touched")
_OPTIONAL_TEXT_FIELDS = ("current_item", "worktree", "branch", "last_commit")


@dataclass(frozen=True)
class CheckpointPaths:
    machine: Path
    human: Path


def validate_checkpoint(value: Any) -> dict[str, Any]:
    """Validate a complete checkpoint record and return its plain data."""
    if not isinstance(value, dict):
        raise TypeError("checkpoint must be an object")
    missing = [field for field in _REQUIRED_FIELDS if field not in value]
    if missing:
        raise ValueError(f"missing checkpoint fields: {', '.join(missing)}")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    for field in ("session_id", "harness", "role"):
        if not isinstance(value[field], str) or not value[field]:
            raise ValueError(f"{field} must be a non-empty string")
    if type(value["turn"]) is not int or value["turn"] < 1:
        raise ValueError("turn must be a positive integer")
    for field in _OPTIONAL_TEXT_FIELDS:
        if value[field] is not None and not isinstance(value[field], str):
            raise ValueError(f"{field} must be a string or null")
    position = value["queue_position"]
    if position is not None and (type(position) is not int or position < 1):
        raise ValueError("queue_position must be a positive integer or null")
    for field in _LIST_FIELDS:
        rows = value[field]
        if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
            raise ValueError(f"{field} must be a list of strings")
    usage = value["token_usage"]
    if not isinstance(usage, dict) or usage.get("status") not in {
        "reported",
        "unavailable",
    }:
        raise ValueError("token_usage must state reported or unavailable")
    total = usage.get("cumulative_tokens")
    if usage["status"] == "reported" and (type(total) is not int or total < 0):
        raise ValueError("reported token_usage needs non-negative cumulative_tokens")
    if usage["status"] == "unavailable" and total is not None:
        raise ValueError("unavailable token_usage must have null cumulative_tokens")
    return value


def render_checkpoint(value: Any) -> str:
    """Render a validated checkpoint for people without changing its data."""
    record = validate_checkpoint(value)
    lines = [
        f"# Turn checkpoint {record['turn']}",
        "",
        f"- Role: {record['role']} ({record['harness']})",
        f"- Session: {record['session_id']}",
        f"- Current item: {record['current_item'] or 'none recorded'}",
        f"- Worktree: {record['worktree'] or 'unknown'}",
        f"- Branch: {record['branch'] or 'unknown'}",
        f"- Last commit: {record['last_commit'] or 'unknown'}",
        f"- Queue position: {record['queue_position'] or 'unknown'}",
        f"- Token usage: {_render_usage(record['token_usage'])}",
    ]
    for field, label in (
        ("decisions_made", "Decisions made"),
        ("pending_findings", "Pending findings"),
        ("next_actions", "Next actions"),
        ("files_touched", "Files touched"),
    ):
        lines.extend((f"- {label}:", *[f"  - {row}" for row in record[field]]))
        if not record[field]:
            lines.append("  - none")
    return "\n".join(lines) + "\n"


def write_checkpoint(checkpoint_root: Path, value: Any) -> CheckpointPaths:
    """Persist one checkpoint turn, its human rendering, and latest pointers."""
    record = validate_checkpoint(value)
    directory = (
        checkpoint_root
        / "sessions"
        / hashlib.sha256(record["session_id"].encode()).hexdigest()[:16]
    )
    directory.mkdir(parents=True, exist_ok=True)
    turn = record["turn"]
    history = CheckpointPaths(
        directory / f"turn-{turn:04d}.json",
        directory / f"turn-{turn:04d}.md",
    )
    rendered = render_checkpoint(record)
    _atomic_write(history.machine, _json(record))
    _atomic_write(history.human, rendered)
    _atomic_write(directory / "latest.json", _json(record))
    _atomic_write(directory / "latest.md", rendered)
    _atomic_write(checkpoint_root / "latest.json", _json(record))
    _atomic_write(checkpoint_root / "latest.md", rendered)
    return history


def read_checkpoint(path: Path) -> dict[str, Any]:
    """Read and validate a checkpoint JSON file."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read checkpoint {path}: {error}") from error
    return validate_checkpoint(value)


def resume_prompt(value: Any) -> str:
    """Build a resume prompt exclusively from a checkpoint record."""
    record = validate_checkpoint(value)
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)
    return (
        "Resume this pipeline session from the structured checkpoint below. "
        "Treat it as the source of current state; continue its next_actions.\n\n"
        f"```json\n{serialized}\n```\n"
    )


def handoff_reason(role: str, tokens: int | None, turns: int) -> str | None:
    """Return the boundary handoff reason for a supported pipeline role."""
    if role in {"builder", "reviewer"}:
        if tokens is not None and tokens >= WORKER_HARD_STOP:
            return "hard-stop"
        if tokens is not None and tokens >= WORKER_TOKEN_LIMIT:
            return "threshold"
        if turns >= WORKER_TURN_LIMIT:
            return "turn-limit"
    elif role == "orchestrator" and tokens is not None:
        if tokens >= ORCHESTRATOR_TOKEN_LIMIT:
            return "threshold"
    return None


def observe_activity(
    turns: int, previous_cursor: str | None, current_cursor: str | None
) -> tuple[int, str | None]:
    """Count one newly observed activity cursor, ignoring retries and missing data."""
    if current_cursor is None or current_cursor == previous_cursor:
        return turns, previous_cursor
    return turns + 1, current_cursor


def check_paseo_slot(
    plan_dir: Path,
    slot: str,
    role: str,
    item: str,
    status: Any,
) -> dict[str, Any]:
    """Persist one Paseo status observation and gate checkpoint or handoff work."""
    if role not in {"builder", "reviewer", "orchestrator"}:
        raise ValueError("role must be builder, reviewer, or orchestrator")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", slot):
        raise ValueError("slot must be a safe path component")
    if not item.strip():
        raise ValueError("item must be non-empty")
    plan_dir = plan_dir.resolve()
    if not (plan_dir / "plan.md").is_file():
        raise ValueError(f"plan directory has no plan.md: {plan_dir}")
    snapshot = _paseo_snapshot(status)
    if snapshot is None:
        return {
            "action": "one_shot_required",
            "reason": (
                "Paseo status must expose agentId, activityCursor, and "
                "contextWindowUsedTokens"
            ),
            "slot": slot,
        }

    state_dir = plan_dir / "notes" / "slot-turns"
    state_path = state_dir / f"{slot}.json"
    lock_path = state_dir / f".{slot}.lock"
    state_dir.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            result = _check_paseo_slot_locked(
                plan_dir, state_path, slot, role, item, snapshot
            )
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return result


def _plan_working_dir(plan_dir: Path) -> Path | None:
    """Return the working directory of a plan stored under <working>/plans."""
    return plan_dir.parent.parent if plan_dir.parent.name == "plans" else None


def _open_slot_store(plan_dir: Path) -> Any | None:
    """Open the durable slot store, or None when it is read-only (markdown)."""
    working = _plan_working_dir(plan_dir)
    if working is None:
        return None
    from varde_data.config import load_data_config
    from varde_data.errors import DataError
    from varde_data.open import open_data

    try:
        return open_data(working, load_data_config()).slots
    except DataError, OSError, sqlite3.Error:
        return None


def _slot_epoch(
    store: Any, plan_dir: Path, state: dict[str, Any], agent_id: str
) -> int | None:
    """Return the epoch this agent registered with, adopting one when unknown."""
    epoch = state.get("slot_epoch")
    if type(epoch) is int:
        return epoch
    current = _slot_owned_by(store, plan_dir, state["slot"], state["role"], agent_id)
    if current is None:
        return None
    state["slot_epoch"] = current.epoch
    return current.epoch


def _record_slot_turn(
    store: Any | None, plan_dir: Path, state: dict[str, Any], snapshot: dict[str, Any]
) -> None:
    """Mirror a counted turn into the slot store; JSON stays the projection.

    The projection records the epoch this agent registered with, so a replaced
    agent's heartbeat is refused instead of renewing the replacement's lease.
    """
    turns = state.get("turn_count")
    if store is None or type(turns) is not int:
        return
    from varde_data.errors import DataError

    try:
        epoch = _slot_epoch(store, plan_dir, state, state["agent_id"])
        if epoch is None:
            return
        store.heartbeat(
            state["slot"],
            epoch=epoch,
            progress_note=state["item"],
            context_tokens=snapshot["context_tokens"],
            turn_count=turns,
        )
    except DataError, OSError, sqlite3.Error:
        return


def _slot_owned_by(
    store: Any, plan_dir: Path, slot: str, role: str, agent_id: str
) -> Any | None:
    """Return this agent's slot row, registering the slot when it is missing."""
    from varde_data.errors import DataError, NotFound

    try:
        current = store.show(slot)
    except NotFound:
        try:
            current = store.register(
                slot,
                plan_id=plan_dir.name,
                role=role,
                agent_ref=agent_id,
                session_id=agent_id,
            )
        except DataError, OSError, sqlite3.Error:
            return None
    return current if current.agent_ref == agent_id else None


def _paseo_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    status = _status_object(value)
    if status is None:
        return None
    agent_id = _first_string(status, "agentId", "agent_id", "id")
    cursor = _first_string(
        status,
        "activityCursor",
        "activity_cursor",
        "lastActivityCursor",
        "last_activity_cursor",
    )
    tokens = status.get(
        "contextWindowUsedTokens", status.get("context_window_used_tokens")
    )
    if agent_id is None or cursor is None or type(tokens) is not int or tokens < 0:
        return None
    usage = status.get("usage")
    cumulative = status.get("totalTokens", status.get("total_tokens"))
    if isinstance(usage, dict):
        cumulative = usage.get("total_tokens", cumulative)
    if type(cumulative) is not int or cumulative < 0:
        cumulative = None
    return {
        "agent_id": agent_id,
        "activity_cursor": cursor,
        "context_tokens": tokens,
        "cumulative_tokens": cumulative,
    }


def _status_object(value: Any, depth: int = 0) -> dict[str, Any] | None:  # noqa: PLR0911
    if depth > 5:
        return None
    if isinstance(value, dict):
        cursor_fields = {
            "activityCursor",
            "activity_cursor",
            "lastActivityCursor",
            "last_activity_cursor",
        }
        if cursor_fields.intersection(value):
            return value
        for key in ("structuredContent", "data", "agent", "status", "snapshot"):
            status = _status_object(value.get(key), depth + 1)
            if status is not None:
                return status
        return _status_object(value.get("content"), depth + 1)
    if isinstance(value, list):
        for item in value:
            status = _status_object(item, depth + 1)
            if status is not None:
                return status
        return None
    if isinstance(value, str):
        try:
            return _status_object(json.loads(value), depth + 1)
        except json.JSONDecodeError:
            return None
    return None


def _first_string(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _check_paseo_slot_locked(
    plan_dir: Path,
    state_path: Path,
    slot: str,
    role: str,
    item: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    state = _read_slot_state(state_path)
    agent_id = snapshot["agent_id"]
    if state and state.get("handoff_pending_turn") is not None:
        if state.get("agent_id") != agent_id:
            return _slot_result(state, slot, "handoff_required")
        return _finish_slot_boundary(plan_dir, state_path, state, snapshot)
    if (
        state
        and state.get("handoff_completed_turn") == state.get("turn_count")
        and state.get("agent_id") == agent_id
    ):
        return {
            **_slot_result(state, slot, "handoff_completed"),
            "reason": (
                "launch and bind a replacement agent before checking this slot again"
            ),
        }
    if state and state.get("agent_id") != agent_id:
        if state.get("handoff_completed_turn") != state.get("turn_count"):
            return {
                "action": "one_shot_required",
                "reason": "a replacement slot requires a completed handoff record",
                "slot": slot,
            }
        state = None

    if state is None:
        state = {
            "schema_version": SCHEMA_VERSION,
            "slot": slot,
            "role": role,
            "item": item,
            "agent_id": agent_id,
            "turn_count": 0,
            "last_activity_cursor": None,
            "handoff_pending_turn": None,
            "handoff_completed_turn": None,
        }
    if state.get("role") != role or state.get("item") != item:
        return {
            "action": "one_shot_required",
            "reason": (
                "slot role or item changed without completing and reopening the slot"
            ),
            "slot": slot,
        }

    turns, cursor = observe_activity(
        int(state.get("turn_count", 0)),
        state.get("last_activity_cursor"),
        snapshot["activity_cursor"],
    )
    changed = cursor != state.get("last_activity_cursor")
    state.update(
        agent_id=agent_id,
        turn_count=turns,
        last_activity_cursor=cursor,
        context_window_used_tokens=snapshot["context_tokens"],
    )
    record_usage(
        plan_dir / "notes" / "token-ledger.json",
        item,
        agent_id,
        snapshot["cumulative_tokens"],
    )
    reason = handoff_reason(role, snapshot["context_tokens"], turns)
    if changed:
        state["checkpoint_pending_turn"] = turns
        state["handoff_pending_turn"] = turns if reason else None
        state["handoff_reason"] = reason
    _record_slot_turn(_open_slot_store(plan_dir), plan_dir, state, snapshot)
    _atomic_write(state_path, _json(state))
    if state.get("checkpoint_pending_turn") == turns:
        return _finish_slot_boundary(plan_dir, state_path, state, snapshot)
    return _slot_result(state, slot, "continue")


def _finish_slot_boundary(
    plan_dir: Path,
    state_path: Path,
    state: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:

    slot = state["slot"]
    role = state["role"]
    item = state["item"]
    turn = state.get("checkpoint_pending_turn")
    if type(turn) is not int:
        turn = state.get("handoff_pending_turn")
    checkpoint_root = plan_dir / "notes" / "checkpoints" / f"{plan_dir.name}-{role}"
    checkpoint_path = checkpoint_root / "latest.json"
    try:
        record = read_checkpoint(checkpoint_path)
    except ValueError:
        record = None
    matches = (
        record is not None
        and record["turn"] == turn
        and record["session_id"] == snapshot["agent_id"]
        and record["role"] == role
        and record["current_item"] == item
    )
    if not matches:
        _atomic_write(state_path, _json(state))
        return {
            **_slot_result(state, slot, "checkpoint_required"),
            "checkpoint": str(checkpoint_path),
            "prompt": (
                f"Complete turn {turn} for {role} in item {item}. Write the full "
                f"structured checkpoint for Paseo agent {snapshot['agent_id']} "
                f"to {checkpoint_path}, then run the slot check again."
            ),
        }
    state["checkpoint_pending_turn"] = None
    _atomic_write(state_path, _json(state))
    if state.get("handoff_pending_turn") == turn:
        return {
            **_slot_result(state, slot, "handoff_required"),
            "checkpoint": str(checkpoint_path),
            "resume_prompt": resume_prompt(record),
            "reason": state.get("handoff_reason"),
        }
    return _slot_result(state, slot, "continue")


def _read_slot_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read slot state {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"invalid slot state: {path}")
    return value


def _slot_result(state: dict[str, Any], slot: str, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "slot": slot,
        "agent_id": state.get("agent_id"),
        "turn_count": state.get("turn_count"),
    }


def complete_paseo_handoff(plan_dir: Path, slot: str, agent_id: str, turn: int) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", slot):
        return False
    state_dir = plan_dir / "notes" / "slot-turns"
    state_path = state_dir / f"{slot}.json"
    lock_path = state_dir / f".{slot}.lock"
    if not state_dir.is_dir():
        return False
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = _read_slot_state(state_path)
            if (
                state is None
                or state.get("agent_id") != agent_id
                or state.get("handoff_pending_turn") != turn
                or state.get("checkpoint_pending_turn") is not None
            ):
                return False
            state["handoff_completed_turn"] = turn
            state["handoff_pending_turn"] = None
            state["handoff_reason"] = None
            _atomic_write(state_path, _json(state))
            _record_slot_handoff(plan_dir, slot, state)
            return True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _record_slot_handoff(plan_dir: Path, slot: str, state: dict[str, Any]) -> None:
    """Mark the slot handed off with its exported checkpoint, best effort."""
    agent_id = state.get("agent_id")
    role = state.get("role")
    if not isinstance(agent_id, str) or not isinstance(role, str):
        return
    store = _open_slot_store(plan_dir)
    checkpoint = _checkpoint_text(plan_dir, role)
    if store is None or checkpoint is None:
        return
    from varde_data.errors import DataError

    try:
        epoch = _slot_epoch(store, plan_dir, state, agent_id)
        if epoch is None:
            return
        store.handoff(slot, epoch=epoch, checkpoint=checkpoint)
    except DataError, OSError, sqlite3.Error:
        return


def _checkpoint_text(plan_dir: Path, role: str) -> str | None:
    path = (
        plan_dir / "notes" / "checkpoints" / f"{plan_dir.name}-{role}" / "latest.json"
    )
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def record_usage(
    path: Path, task_id: str, session_id: str, cumulative_tokens: int | None
) -> dict[str, Any]:
    """Update a task ledger using cumulative session snapshots, never deltas."""
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        ledger = {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read token ledger {path}: {error}") from error
    ledger_data = cast("dict[str, Any]", ledger) if isinstance(ledger, dict) else {}
    raw_task = ledger_data.get(task_id)
    task: dict[str, Any] = (
        cast("dict[str, Any]", raw_task)
        if isinstance(raw_task, dict)
        else {"sessions": {}}
    )
    raw_sessions = task.get("sessions")
    sessions: dict[str, Any] = (
        cast("dict[str, Any]", raw_sessions) if isinstance(raw_sessions, dict) else {}
    )
    if not isinstance(sessions, dict):
        sessions = {}
    previous = sessions.get(session_id)
    if cumulative_tokens is None:
        if not (isinstance(previous, dict) and previous.get("status") == "reported"):
            sessions[session_id] = {"status": "unavailable"}
    else:
        if cumulative_tokens < 0:
            raise ValueError("cumulative_tokens must be non-negative")
        previous_total = (
            previous.get("cumulative_tokens") if isinstance(previous, dict) else None
        )
        total = max(cumulative_tokens, previous_total or 0)
        sessions[session_id] = {
            "status": "reported",
            "cumulative_tokens": total,
        }
    task["sessions"] = sessions
    task["cumulative_tokens"] = sum(
        item["cumulative_tokens"]
        for item in sessions.values()
        if isinstance(item, dict)
        and item.get("status") == "reported"
        and isinstance(item.get("cumulative_tokens"), int)
    )
    task["status"] = (
        "reported"
        if any(item.get("status") == "reported" for item in sessions.values())
        else "unavailable"
    )
    ledger_data[task_id] = task
    _atomic_write(path, _json(ledger_data))
    return task


def _render_usage(value: dict[str, Any]) -> str:
    if value["status"] == "unavailable":
        return "unavailable"
    return f"{value['cumulative_tokens']} cumulative tokens"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary_name)
        raise
