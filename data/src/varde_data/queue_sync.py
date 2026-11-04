"""Import and export queue markdown through the shared SQLite queue store."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.queue_md import (
    QueueDocument,
    QueueRow,
    parse_depends_cell,
    parse_queue_md,
    render_queue_md,
)
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import queue_database_for
from varde_data.records.queue import QueueItemInput


@dataclass(frozen=True)
class ImportReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def _working_dir(path: Path) -> Path:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == "plans":
            return parent.parent
    return resolved.parent


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _item_values(row: QueueRow, queue_name: str, order: int) -> QueueItemInput:
    values = row.values
    depends = values.get("depends_on / serialize-with", "")
    deps, serial = parse_depends_cell(depends)
    try:
        priority = int(values.get("priority", "0") or "0")
    except ValueError:
        priority = 0
    return QueueItemInput(
        id=values.get("id", ""),
        plan_dir=values.get("plan dir", ""),
        findings=values.get("findings", ""),
        owned_files=values.get("owned files", ""),
        depends_cell=depends,
        depends_on=tuple(deps),
        serialize_with=tuple(serial),
        priority=priority,
        state=values.get("state", "queued"),
        planned_at=values.get("planned_at") or None,
        plan_reviewed_at=values.get("plan_reviewed_at") or None,
        build_started_at=values.get("build_started_at") or None,
        build_done_at=values.get("build_done_at") or None,
        merged_at=values.get("merged_at") or None,
        queue_name=queue_name,
        row_order=order,
        extra={"markdown_values": values},
    )


def import_queue_md(
    path: str | Path, queue_name: str, *, database: Path | None = None
) -> ImportReport:
    """Import rows without deleting absent store items; malformed files are skipped."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    try:
        document = parse_queue_md(text)
    except ValueError as exc:
        return ImportReport(skipped=(str(exc),))
    if not document.header:
        return ImportReport(skipped=("queue markdown contains no pipe table",))
    _validate_ids(document)
    working = _working_dir(source)
    content_hash = _hash(text)
    with operation(working):
        store = SQLiteQueue(database or queue_database_for(working))
        with store._connection() as db:
            configure_store(db)
            previous = db.execute(
                "SELECT last_export_hash FROM queue_meta WHERE queue_name=?",
                (queue_name,),
            ).fetchone()
            matches_export = previous is not None and previous[0] == content_hash
        if matches_export:
            conflicts = []
            unchanged = 0
            for order, row in enumerate(document.rows):
                item = _item_values(row, queue_name, order)
                try:
                    stored = store.get(queue_name, item.id)
                except NotFound:
                    conflicts.append(item.id)
                    continue
                if not _same_item(stored, item):
                    conflicts.append(item.id)
                else:
                    unchanged += 1
            return ImportReport(unchanged=unchanged, conflicts=tuple(conflicts))
        added = updated = unchanged = 0
        conflicts = []
        for order, row in enumerate(document.rows):
            item = _item_values(row, queue_name, order)
            try:
                old = store.get(queue_name, item.id)
            except NotFound:
                store.enqueue(item)
                added += 1
                _record_import_event(store, item.id, None, item.state)
                continue
            baseline = (old.extra or {}).get("markdown_values")
            changed_cells = (
                {
                    key
                    for key, value in row.values.items()
                    if not isinstance(baseline, dict) or baseline.get(key) != value
                }
                if isinstance(baseline, dict)
                else set(row.values)
            )
            if not changed_cells:
                if not _same_item(old, item):
                    conflicts.append(item.id)
                unchanged += 1
                continue
            _update_item(store, _merge_changed_cells(old, item, row, changed_cells))
            updated += 1
            _record_import_event(store, item.id, old.state, item.state)
        with store._connection() as db:
            db.execute(
                "INSERT INTO queue_meta(queue_name,last_export_hash,header) "
                "VALUES(?,?,?) "
                "ON CONFLICT(queue_name) DO UPDATE SET "
                "last_export_hash=excluded.last_export_hash,header=excluded.header",
                (
                    queue_name,
                    None,
                    json.dumps(_document_header(document)),
                ),
            )
        return ImportReport(added, updated, unchanged, conflicts=tuple(conflicts))


def _validate_ids(document: QueueDocument) -> None:
    seen: set[str] = set()
    for index, row in enumerate(document.rows, start=1):
        item_id = row.values.get("id", "").strip()
        if not item_id:
            raise Invalid(f"queue row {index} has an empty id")
        if item_id in seen:
            raise Invalid(f"queue row {index} has duplicate id {item_id!r}")
        seen.add(item_id)


def _same_item(stored, imported: QueueItemInput) -> bool:
    return all(
        getattr(stored, field) == getattr(imported, field)
        for field in (
            "plan_dir",
            "findings",
            "owned_files",
            "depends_cell",
            "priority",
            "state",
            "planned_at",
            "plan_reviewed_at",
            "build_started_at",
            "build_done_at",
            "merged_at",
        )
    )


def _merge_changed_cells(old, item: QueueItemInput, row: QueueRow, changed: set[str]):
    """Apply only cells changed since the stored Markdown baseline."""
    fields = {
        "plan dir": "plan_dir",
        "findings": "findings",
        "owned files": "owned_files",
        "depends_on / serialize-with": "depends_cell",
        "state": "state",
        "planned_at": "planned_at",
        "plan_reviewed_at": "plan_reviewed_at",
        "build_started_at": "build_started_at",
        "build_done_at": "build_done_at",
        "merged_at": "merged_at",
    }
    updates = {field: getattr(old, field) for field in fields.values()}
    for cell, field in fields.items():
        if cell in changed:
            updates[field] = getattr(item, field)
    if "priority" in changed:
        updates["priority"] = item.priority
    values = dict(row.values)
    extra = dict(old.extra or {})
    extra["markdown_values"] = values
    return QueueItemInput(
        id=old.id,
        queue_name=old.queue_name,
        row_order=item.row_order,
        depends_on=item.depends_on
        if "depends_on / serialize-with" in changed
        else old.depends_on,
        serialize_with=item.serialize_with
        if "depends_on / serialize-with" in changed
        else old.serialize_with,
        extra=extra,
        **updates,
    )


def _document_header(document: QueueDocument) -> dict[str, str | list[str]]:
    return {
        "title": document.title,
        "preamble": document.preamble,
        "header": list(document.header),
        "trailing": document.trailing,
        "separator": document.separator,
        "newline": document.newline,
        "header_raw": document.header_raw,
    }


def _record_import_event(
    store: SQLiteQueue, item_id: str, old: str | None, new: str
) -> None:
    with store._connection() as db:
        db.execute(
            "INSERT INTO queue_events "
            "(item_id,at,actor,kind,from_state,to_state,source) "
            "VALUES(?,datetime('now'),'markdown','import',?,?,'markdown')",
            (item_id, old, new),
        )


def _update_item(store: SQLiteQueue, item: QueueItemInput) -> None:
    with store._connection() as db:
        db.execute(
            "UPDATE queue_items SET "
            "plan_dir=?,findings=?,owned_files=?,depends_cell=?,depends_on=?,"
            "serialize_with=?,priority=?,state=?,planned_at=?,plan_reviewed_at=?,"
            "build_started_at=?,build_done_at=?,merged_at=?,row_order=?,extra=? "
            "WHERE queue_name=? AND id=?",
            (
                item.plan_dir,
                item.findings,
                item.owned_files,
                item.depends_cell,
                json.dumps(item.depends_on),
                json.dumps(item.serialize_with),
                item.priority,
                item.state,
                item.planned_at,
                item.plan_reviewed_at,
                item.build_started_at,
                item.build_done_at,
                item.merged_at,
                item.row_order,
                json.dumps(item.extra or {}, sort_keys=True),
                item.queue_name,
                item.id,
            ),
        )


def export_queue_md(working: str | Path, queue_name: str) -> str:
    """Render queue rows from SQLite using the stored document header."""
    working = Path(working)
    with operation(working):
        database = queue_database_for(working)
        if not database.is_file():
            raise Conflict(f"queue {queue_name!r} has not been imported")
        store = SQLiteQueue(database)
        with store._connection() as db:
            meta = db.execute(
                "SELECT header FROM queue_meta WHERE queue_name=?", (queue_name,)
            ).fetchone()
            if meta is None:
                raise Conflict(f"queue {queue_name!r} has not been imported")
            header = json.loads(meta[0])
        document = QueueDocument(
            header["title"],
            header["preamble"],
            tuple(header["header"]),
            (),
            header["trailing"],
            header["separator"],
            header["newline"],
            header["header_raw"],
        )
        rows = []
        for item in store.list(queue_name):
            raw_values = item.extra.get("markdown_values", {}) if item.extra else {}
            values = (
                {
                    key: value
                    for key, value in raw_values.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
                if isinstance(raw_values, Mapping)
                else {}
            )
            values.update(
                {
                    "id": item.id,
                    "plan dir": item.plan_dir,
                    "findings": item.findings,
                    "owned files": item.owned_files,
                    "depends_on / serialize-with": item.depends_cell,
                    "state": item.state,
                    "planned_at": item.planned_at or "",
                    "plan_reviewed_at": item.plan_reviewed_at or "",
                    "build_started_at": item.build_started_at or "",
                    "build_done_at": item.build_done_at or "",
                    "merged_at": item.merged_at or "",
                }
            )
            rows.append(
                QueueRow(
                    values,
                    {k: v for k, v in values.items() if k not in document.header},
                    "",
                )
            )
        return render_queue_md(
            QueueDocument(
                document.title,
                document.preamble,
                document.header,
                tuple(rows),
                document.trailing,
                document.separator,
                document.newline,
                document.header_raw,
            )
        )


def record_queue_md_export(working: str | Path, queue_name: str, rendered: str) -> None:
    """Record an export only after the caller successfully writes ``rendered``."""
    root = Path(working)
    with operation(root):
        database = queue_database_for(root)
        if not database.is_file():
            raise Conflict(f"queue {queue_name!r} has not been imported")
        store = SQLiteQueue(database)
        with store._connection() as db:
            for row in parse_queue_md(rendered).rows:
                stored = db.execute(
                    "SELECT extra FROM queue_items WHERE queue_name=? AND id=?",
                    (queue_name, row.values.get("id", "")),
                ).fetchone()
                if stored is None:
                    continue
                extra = json.loads(stored[0] or "{}")
                extra["markdown_values"] = dict(row.values)
                db.execute(
                    "UPDATE queue_items SET extra=? WHERE queue_name=? AND id=?",
                    (json.dumps(extra, sort_keys=True), queue_name, row.values["id"]),
                )
            db.execute(
                "UPDATE queue_meta SET last_export_hash=? WHERE queue_name=?",
                (_hash(rendered), queue_name),
            )
