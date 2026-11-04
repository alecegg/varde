"""Import and export a plan's lossless line queue through SQLite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import NotFound
from varde_data.queue_line import (
    LineQueue,
    LineQueueRow,
    parse_line_queue,
    validate_line_queue,
)
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import queue_database_for
from varde_data.queue_sync import ImportReport
from varde_data.records.queue import QueueItemInput


def _working_dir(plan_dir: Path) -> Path:
    resolved = plan_dir.resolve()
    for parent in resolved.parents:
        if parent.name == "plans":
            return parent.parent
    return resolved.parent


def line_queue_name(plan_dir: str | Path) -> str:
    """Return a stable queue key unique to a plan directory."""
    return f"line:{_plan_identity(plan_dir)}"


def _plan_identity(plan_dir: str | Path) -> str:
    plan_dir = Path(plan_dir)
    working = _working_dir(plan_dir)
    return plan_dir.resolve().relative_to(working.resolve()).as_posix()


def _path(plan_dir: Path) -> Path:
    return plan_dir / "notes" / "queue.md"


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _encode_layout(queue: LineQueue, rows: tuple[LineQueueRow, ...]) -> str:
    layout = [
        {"raw": value} if kind == "raw" else {"id": rows[int(value)].task}
        for kind, value in queue.layout
    ]
    return json.dumps(
        {
            "layout": layout,
            "header": list(queue.header),
            "passthrough": list(queue.passthrough),
        }
    )


def _decode_layout(value: str) -> dict[str, object]:
    try:
        data = json.loads(value)
    except TypeError, json.JSONDecodeError:
        return {"layout": [], "header": [], "passthrough": []}
    return (
        data
        if isinstance(data, dict)
        else {"layout": [], "header": [], "passthrough": []}
    )


def _import_text(
    plan_dir: Path, text: str, *, database: Path | None = None
) -> ImportReport:
    parsed = parse_line_queue(text)
    queue_name = line_queue_name(plan_dir)
    working = _working_dir(plan_dir)
    store = SQLiteQueue(database or queue_database_for(working))
    with store._connection() as db:
        configure_store(db)
        meta = db.execute(
            "SELECT last_export_hash FROM queue_meta WHERE queue_name=?", (queue_name,)
        ).fetchone()
        if meta is not None and meta[0] == _hash(text):
            return ImportReport(unchanged=len(parsed.rows))
    ids = [row.task for row in parsed.rows]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        return ImportReport(
            conflicts=tuple(f"duplicate task id: {item}" for item in duplicates)
        )
    added = updated = unchanged = 0
    row_order: dict[str, int] = {}
    for order, row in enumerate(parsed.rows):
        row_order[row.task] = order
        item = QueueItemInput(
            id=f"{queue_name}#{row.task}",
            plan_dir=_plan_identity(plan_dir),
            queue_name=queue_name,
            row_order=order,
            state="queued",
            extra={
                "task": row.task,
                "markdown_values": dict(row.markdown_values),
                "tail": row.tail,
                "line": row.raw,
                "strict": row.strict,
            },
        )
        try:
            old = store.get(queue_name, item.id)
        except NotFound:
            store.enqueue(item)
            added += 1
            continue
        if old.extra == item.extra and old.row_order == order:
            unchanged += 1
        else:
            with store._connection() as db:
                db.execute(
                    "UPDATE queue_items SET row_order=?,extra=? "
                    "WHERE queue_name=? AND id=?",
                    (
                        order,
                        json.dumps(item.extra or {}, sort_keys=True),
                        queue_name,
                        item.id,
                    ),
                )
            updated += 1
    with store._connection() as db:
        db.execute(
            "INSERT INTO queue_meta(queue_name,last_export_hash,header) VALUES(?,?,?) "
            "ON CONFLICT(queue_name) DO UPDATE SET last_export_hash=NULL,"
            "header=excluded.header",
            (queue_name, None, _encode_layout(parsed, parsed.rows)),
        )
    return ImportReport(added, updated, unchanged)


def import_line_queue(
    plan_dir: str | Path, *, database: Path | None = None
) -> ImportReport:
    """Import the queue file for a plan directory."""
    plan = Path(plan_dir)
    path = _path(plan)
    text = _read_text(path)
    with operation(_working_dir(plan)):
        return _import_text(plan, text, database=database)


def _render_store(plan_dir: Path, store: SQLiteQueue, header: dict[str, object]) -> str:
    items = {
        str((item.extra or {}).get("task", item.id)): item
        for item in store.list(line_queue_name(plan_dir))
    }
    output: list[str] = []
    layout = header.get("layout", [])
    if not isinstance(layout, list):
        return ""
    for entry in layout:
        if not isinstance(entry, dict):
            continue
        if "raw" in entry:
            output.append(str(entry["raw"]))
            continue
        item_id = str(entry.get("id", ""))
        item = items.get(item_id)
        if item is None:
            continue
        extra = item.extra or {}
        raw = extra.get("line")
        if isinstance(raw, str):
            output.append(raw)
            continue
        values = extra.get("markdown_values", {})
        fields = (
            [f"{key}:{value}" for key, value in values.items()]
            if isinstance(values, dict)
            else []
        )
        tail = extra.get("tail")
        if isinstance(tail, str) and tail:
            fields.append(tail)
        task = extra.get("task", item.id)
        output.append(" | ".join([str(task), *fields]) + "\n")
    return "".join(output)


def _import_before_export(plan_dir: Path, source: str) -> None:
    report = _import_text(plan_dir, source)
    if report.conflicts:
        validate_line_queue(source, str(_path(plan_dir)))


def export_line_queue(plan_dir: str | Path) -> str:
    """Import file drift first, then render and record the store projection."""
    plan = Path(plan_dir)
    working = _working_dir(plan)
    queue_name = line_queue_name(plan)
    with operation(working):
        store = SQLiteQueue(queue_database_for(working))
        with store._connection() as db:
            configure_store(db)
            previous = db.execute(
                "SELECT last_export_hash,header FROM queue_meta WHERE queue_name=?",
                (queue_name,),
            ).fetchone()
        if previous is None:
            source = _read_text(_path(plan))
            _import_before_export(plan, source)
            with store._connection() as db:
                previous = db.execute(
                    "SELECT last_export_hash,header FROM queue_meta WHERE queue_name=?",
                    (queue_name,),
                ).fetchone()
        else:
            source = _read_text(_path(plan))
            if previous[0] != _hash(source):
                _import_before_export(plan, source)
                with store._connection() as db:
                    previous = db.execute(
                        "SELECT last_export_hash,header FROM queue_meta "
                        "WHERE queue_name=?",
                        (queue_name,),
                    ).fetchone()
        result = _render_store(plan, store, _decode_layout(previous[1]))
        with store._connection() as db:
            db.execute(
                "UPDATE queue_meta SET last_export_hash=? WHERE queue_name=?",
                (_hash(result), queue_name),
            )
        return result
