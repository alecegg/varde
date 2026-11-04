"""Project SQLite plan/task state into Markdown frontmatter and import edits."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from varde_core.frontmatter import parse

from varde_data.backends.sqlite.plan_state import (
    SQLitePlanState,
    _record_transition,
    canonical_plan_dir,
)
from varde_data.errors import Invalid
from varde_data.frontmatter_patch import patch_fields
from varde_data.locking import atomic_write, file_lock
from varde_data.queue_paths import queue_database_for

_PLAN_FIELDS = ("status", "status_at", "owner", "assigned_to", "merge_approved_at")
_TASK_FIELDS = ("status", "status_at")


def export_plan_dir(
    root: Path, plan_dir: str | Path, *, database: Path | None = None
) -> None:
    """Write stored state to plan/task frontmatter without changing other bytes."""
    directory = Path(plan_dir)
    plan_file = _plan_file(directory)
    directory = plan_file.parent
    plan_key = canonical_plan_dir(directory)
    store = SQLitePlanState(database or queue_database_for(root))
    with file_lock(directory / ".plan.lock", timeout=5), store._connection() as db:
        plan = db.execute(
            "SELECT * FROM plan_state WHERE plan_dir=?", (plan_key,)
        ).fetchone()
        tasks = db.execute(
            "SELECT * FROM task_state WHERE plan_dir=?", (plan_key,)
        ).fetchall()
        if plan is not None:
            raw = plan_file.read_bytes()
            updated = _patch(raw, _values(plan, _PLAN_FIELDS), _PLAN_FIELDS)
            _write_if_changed(plan_file, raw, updated)
            db.execute(
                "UPDATE plan_state SET last_export_hash=? WHERE plan_dir=?",
                (_state_hash(updated, _PLAN_FIELDS), plan_key),
            )
        for task in tasks:
            task_file = directory / "tasks" / f"{task['task_id']}.md"
            raw = task_file.read_bytes()
            updated = _patch(raw, _values(task, _TASK_FIELDS), _TASK_FIELDS)
            _write_if_changed(task_file, raw, updated)
            db.execute(
                "UPDATE task_state SET last_export_hash=? "
                "WHERE plan_dir=? AND task_id=?",
                (_state_hash(updated, _TASK_FIELDS), plan_key, task["task_id"]),
            )


def import_plan_dir(
    root: Path, plan_dir: str | Path, *, database: Path | None = None
) -> tuple[str, ...]:
    """Import plan state and return task Markdown paths without state frontmatter."""
    directory = Path(plan_dir)
    plan_file = _plan_file(directory)
    directory = plan_file.parent
    plan_key = canonical_plan_dir(directory)
    store = SQLitePlanState(database or queue_database_for(root))
    with file_lock(directory / ".plan.lock", timeout=5), store._connection() as db:
        plan_row = db.execute(
            "SELECT * FROM plan_state WHERE plan_dir=?", (plan_key,)
        ).fetchone()
        if plan_row is None:
            _import_new_plan(db, plan_file, plan_key)
        else:
            _import_plan(db, plan_row, plan_file, plan_key)
        stored_tasks = {
            row["task_id"]: row
            for row in db.execute(
                "SELECT * FROM task_state WHERE plan_dir=?", (plan_key,)
            ).fetchall()
        }
        skipped: list[str] = []
        for task_file in sorted((directory / "tasks").glob("*.md")):
            if task_state_fields(task_file) is None:
                skipped.append(str(task_file))
                continue
            task_id = task_file.stem
            task_row = stored_tasks.get(task_id)
            if task_row is None:
                _import_new_task(db, task_file, plan_key, task_id)
            else:
                _import_task(db, task_row, task_file, plan_key)
    return tuple(skipped)


def task_state_fields(path: str | Path) -> dict[str, object] | None:
    """Return task state fields, or None when Markdown is not a state document."""
    raw = Path(path).read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    if not normalized.startswith(b"---\n"):
        return None
    fields = _fields(normalized)
    if "status" not in fields:
        return None
    if _text(fields.get("status")) is None:
        raise Invalid(f"task status in {path} must be a scalar")
    return fields


def _plan_file(path: Path) -> Path:
    return path if path.name == "plan.md" else path / "plan.md"


def _import_new_plan(db: sqlite3.Connection, path: Path, plan_dir: str) -> None:
    fields = _fields(path.read_bytes())
    values = {key: _text(fields.get(key)) for key in _PLAN_FIELDS}
    status = values["status"]
    if status is None:
        raise Invalid(f"plan status in {path} must be a scalar")
    digest = _fields_hash(fields, _PLAN_FIELDS)
    db.execute(
        "INSERT INTO plan_state "
        "(plan_dir,status,status_at,owner,assigned_to,"
        "merge_approved_at,last_export_hash) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            plan_dir,
            status,
            values["status_at"],
            values["owner"],
            values["assigned_to"],
            values["merge_approved_at"],
            digest,
        ),
    )
    _record_transition(
        db,
        f"plan:{plan_dir}",
        None,
        status,
        actor="markdown",
        source="markdown",
    )


def _import_new_task(
    db: sqlite3.Connection, path: Path, plan_dir: str, task_id: str
) -> None:
    fields = _fields(path.read_bytes())
    status = _text(fields.get("status"))
    if status is None:
        raise Invalid(f"task status in {path} must be a scalar")
    status_at = _text(fields.get("status_at"))
    digest = _fields_hash(fields, _TASK_FIELDS)
    db.execute(
        "INSERT INTO task_state (plan_dir,task_id,status,status_at,last_export_hash) "
        "VALUES (?,?,?,?,?)",
        (plan_dir, task_id, status, status_at, digest),
    )
    _record_transition(
        db,
        f"task:{plan_dir}:{task_id}",
        None,
        status,
        actor="markdown",
        source="markdown",
    )


def _import_plan(
    db: sqlite3.Connection, row: sqlite3.Row, path: Path, plan_dir: str
) -> None:
    raw = path.read_bytes()
    fields = _fields(raw)
    current_hash = _fields_hash(fields, _PLAN_FIELDS)
    if row["last_export_hash"] is None:
        return
    if current_hash == row["last_export_hash"]:
        return
    previous = row["status"]
    status = fields.get("status")
    if not isinstance(status, str):
        raise Invalid(f"plan status in {path} must be a string")
    db.execute(
        "UPDATE plan_state SET status=?,status_at=?,owner=?,assigned_to=?,"
        "merge_approved_at=?,last_export_hash=? WHERE plan_dir=?",
        (status,)
        + tuple(_text(fields.get(key)) for key in _PLAN_FIELDS[1:])
        + (current_hash, plan_dir),
    )
    _record_transition(
        db, f"plan:{plan_dir}", previous, status, actor="markdown", source="markdown"
    )


def _import_task(
    db: sqlite3.Connection, row: sqlite3.Row, path: Path, plan_dir: str
) -> None:
    raw = path.read_bytes()
    fields = _fields(raw)
    current_hash = _fields_hash(fields, _TASK_FIELDS)
    if row["last_export_hash"] is None:
        return
    if current_hash == row["last_export_hash"]:
        return
    status = fields.get("status")
    if not isinstance(status, str):
        raise Invalid(f"task status in {path} must be a string")
    previous = row["status"]
    db.execute(
        "UPDATE task_state SET status=?,status_at=?,last_export_hash=? "
        "WHERE plan_dir=? AND task_id=?",
        (
            status,
            _text(fields.get("status_at")),
            current_hash,
            plan_dir,
            row["task_id"],
        ),
    )
    _record_transition(
        db,
        f"task:{plan_dir}:{row['task_id']}",
        previous,
        status,
        actor="markdown",
        source="markdown",
    )


def _patch(raw: bytes, fields: dict[str, str], keys: tuple[str, ...]) -> bytes:
    try:
        remove = tuple(key for key in keys if key not in fields)
        return patch_fields(raw, set_fields=fields, remove_fields=remove)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc


def _values(row: sqlite3.Row, keys: tuple[str, ...]) -> dict[str, str]:
    return {key: row[key] for key in keys if isinstance(row[key], str)}


def _fields(raw: bytes) -> dict[str, object]:
    try:
        fields, _ = parse(raw.replace(b"\r\n", b"\n"))
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    return fields


def _state_hash(raw: bytes, keys: tuple[str, ...]) -> str:
    return _fields_hash(_fields(raw), keys)


def _fields_hash(fields: dict[str, object], keys: tuple[str, ...]) -> str:
    encoded = json.dumps(
        {key: _text(fields.get(key)) for key in keys},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_if_changed(path: Path, old: bytes, new: bytes) -> None:
    if old != new:
        atomic_write(path, new, mode=path.stat().st_mode & 0o777)


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise Invalid("plan/task state frontmatter values must be scalar")
