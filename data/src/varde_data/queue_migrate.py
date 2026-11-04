"""Migrate queue and plan workflow state from Markdown to SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from varde_data.backends.sqlite.messages import SQLiteMessages
from varde_data.backends.sqlite.plan_state import initialize_plan_state
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import (
    QUEUE_MARKER_VERSION,
    configure_store,
)
from varde_data.errors import Conflict
from varde_data.locking import atomic_write
from varde_data.plan_state_sync import (
    _fields,
    _text,
    import_plan_dir,
    task_state_fields,
)
from varde_data.queue_line import parse_line_queue
from varde_data.queue_line_sync import (
    _decode_layout,
    _encode_layout,
    import_line_queue,
    line_queue_name,
)
from varde_data.queue_md import QueueDocument, parse_queue_md
from varde_data.queue_mode_lock import barrier
from varde_data.queue_paths import (
    LEGACY_QUEUE_DATABASE,
    QUEUE_DATABASE,
    read_queue_version,
)
from varde_data.queue_sync import (
    _document_header,
    _item_values,
    import_queue_md,
)
from varde_data.records.queue import QueueItemInput
from varde_data.role_queue_merge import QUEUE_VERSION_MARKER, _snapshot

_LINE_MARKER = re.compile(r"\|\s*fix:(?:yes|no)\b")


@dataclass(frozen=True)
class MigrationReport:
    dry_run: bool
    backup: Path | None
    diffs: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    line_queues: tuple[str, ...] = ()
    skipped_lines: tuple[str, ...] = ()
    unknown_formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueueSource:
    path: Path
    text: str
    kind: str
    document: QueueDocument | None = None


@dataclass(frozen=True)
class ExpectedMigration:
    queues: dict[tuple[str, str], QueueItemInput]
    queue_headers: dict[str, dict[str, str | list[str]]]
    plans: dict[str, dict[str, str | None]]
    tasks: dict[tuple[str, str], dict[str, str | None]]
    sources: tuple[QueueSource, ...]
    unknown_formats: tuple[str, ...]
    skipped_task_states: tuple[str, ...]


def _checkpoint(step: str) -> None:
    """Crash injection point used by migration tests."""


def _ensure_legacy_queue_merged(root: Path) -> None:
    if not (root / LEGACY_QUEUE_DATABASE).is_file():
        return
    marker = read_queue_version(root)
    if marker < QUEUE_MARKER_VERSION:
        raise Conflict(
            "legacy SQLite queue remains active; run `varde plan queue "
            "merge-role-inbox` before importing Markdown queue state"
        )


def _queue_files(working: Path) -> list[Path]:
    plans = working / "plans"
    return sorted(plans.rglob("queue.md")) if plans.is_dir() else []


def _plan_dirs(working: Path) -> list[Path]:
    plans = working / "plans"
    return (
        sorted(path.parent for path in plans.rglob("plan.md")) if plans.is_dir() else []
    )


def _queue_name(working: Path, path: Path) -> str:
    return path.resolve().relative_to(working.resolve()).as_posix()


def _source_queue_name(working: Path, source: QueueSource) -> str:
    if source.kind == "line":
        return line_queue_name(source.path.parent.parent)
    return _queue_name(working, source.path)


def _source_queue_path(working: Path, queue_name: str) -> Path:
    if queue_name.startswith("line:"):
        return working / queue_name.removeprefix("line:") / "notes" / "queue.md"
    return working / queue_name


def _queue_sources(working: Path) -> tuple[QueueSource, ...]:
    sources: list[QueueSource] = []
    for path in _queue_files(working):
        text = path.read_text(encoding="utf-8")
        try:
            document = parse_queue_md(text)
        except ValueError:
            document = None
        if document is not None and document.header:
            sources.append(QueueSource(path, text, "table", document))
            continue
        if path.parent.name == "notes" and _LINE_MARKER.search(text):
            sources.append(QueueSource(path, text, "line"))
            continue
        sources.append(QueueSource(path, text, "unknown"))
    return tuple(sources)


def _markdown_states(path: Path, fields: tuple[str, ...]) -> dict[str, str | None]:
    parsed = _fields(path.read_bytes())
    return {field: _text(parsed.get(field)) for field in fields}


def _line_queue_items(source: QueueSource) -> tuple[QueueItemInput, ...]:
    plan_dir = source.path.parent.parent
    queue_name = line_queue_name(plan_dir)
    plan_identity = queue_name.removeprefix("line:")
    return tuple(
        QueueItemInput(
            id=f"{queue_name}#{row.task}",
            plan_dir=plan_identity,
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
        for order, row in enumerate(parse_line_queue(source.text).rows)
    )


def _expected(working: Path) -> ExpectedMigration:
    queues: dict[tuple[str, str], QueueItemInput] = {}
    queue_headers: dict[str, dict[str, str | list[str]]] = {}
    plans: dict[str, dict[str, str | None]] = {}
    tasks: dict[tuple[str, str], dict[str, str | None]] = {}
    skipped_task_states: list[str] = []
    sources = _queue_sources(working)
    for source in sources:
        if source.kind == "line":
            for item in _line_queue_items(source):
                queues[item.queue_name, item.id] = item
            continue
        if source.kind != "table" or source.document is None:
            continue
        name = _queue_name(working, source.path)
        queue_headers[name] = _document_header(source.document)
        for order, row in enumerate(source.document.rows):
            item = _item_values(row, name, order)
            queues[name, item.id] = item
    for directory in _plan_dirs(working):
        key = str(directory.resolve())
        plans[key] = _markdown_states(
            directory / "plan.md",
            ("status", "status_at", "owner", "assigned_to", "merge_approved_at"),
        )
        for path in sorted((directory / "tasks").glob("*.md")):
            fields = task_state_fields(path)
            if fields is None:
                skipped_task_states.append(str(path))
                continue
            tasks[key, path.stem] = {
                field: _text(fields.get(field)) for field in ("status", "status_at")
            }
    unknown = tuple(str(source.path) for source in sources if source.kind == "unknown")
    return ExpectedMigration(
        queues,
        queue_headers,
        plans,
        tasks,
        sources,
        unknown,
        tuple(skipped_task_states),
    )


def _read_only_database(working: Path) -> sqlite3.Connection | None:
    database = working / QUEUE_DATABASE
    if not database.is_file():
        return None
    return sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)


def _collision_error(working: Path, expected: ExpectedMigration) -> Conflict | None:
    owners: dict[str, QueueSource] = {}
    for source in expected.sources:
        if source.kind == "table" and source.document is not None:
            item_ids = (row.values.get("id", "") for row in source.document.rows)
        elif source.kind == "line":
            item_ids = (item.id for item in _line_queue_items(source))
        else:
            continue
        for item_id in item_ids:
            previous = owners.get(item_id)
            if previous is not None and previous.path != source.path:
                return Conflict(
                    f"queue id {item_id!r} appears in both "
                    f"{previous.path} and {source.path}"
                )
            owners[item_id] = source
    database = _read_only_database(working)
    if database is None:
        return None
    try:
        tables = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='queue_items'"
        ).fetchone()
        if tables is None or not owners:
            return None
        rows = database.execute("SELECT id,queue_name FROM queue_items")
        for item_id, queue_name in rows:
            source = owners.get(item_id)
            if source is None:
                continue
            if queue_name != _source_queue_name(working, source):
                prior = _source_queue_path(working, queue_name)
                return Conflict(
                    f"queue id {item_id!r} appears in both {prior} and {source.path}"
                )
        return None
    finally:
        database.close()


def _verify_table_headers(
    db: sqlite3.Connection, expected_headers: dict[str, dict[str, str | list[str]]]
) -> list[str]:
    diffs: list[str] = []
    for queue_name, expected in expected_headers.items():
        actual = db.execute(
            "SELECT header FROM queue_meta WHERE queue_name=?", (queue_name,)
        ).fetchone()
        if actual is None:
            diffs.append(f"queue metadata {queue_name}: missing")
            continue
        try:
            header = json.loads(actual[0])
        except TypeError, json.JSONDecodeError:
            header = None
        if header != expected:
            diffs.append(
                f"queue metadata {queue_name} header: "
                f"expected {expected!r}, got {header!r}"
            )
    return diffs


def _verify_line_queues(
    working: Path, db: sqlite3.Connection, sources: tuple[QueueSource, ...]
) -> list[str]:
    diffs: list[str] = []
    for source in sources:
        if source.kind != "line":
            continue
        plan_dir = source.path.parent.parent
        queue_name = line_queue_name(plan_dir)
        metadata = db.execute(
            "SELECT header FROM queue_meta WHERE queue_name=?", (queue_name,)
        ).fetchone()
        if metadata is None:
            diffs.append(f"line queue metadata {queue_name}: missing")
            continue
        parsed = parse_line_queue(source.text)
        if metadata[0] != _encode_layout(parsed, parsed.rows):
            diffs.append(f"line queue metadata {queue_name} header differs from file")
        rows = db.execute(
            "SELECT id,extra FROM queue_items WHERE queue_name=? "
            "ORDER BY priority,row_order,id",
            (queue_name,),
        )
        items: dict[str, dict[str, object]] = {}
        for row in rows:
            extra: dict[str, object] = json.loads(row["extra"] or "{}")
            task = str(extra.get("task", row["id"]))
            items[task] = extra
        rendered = _render_line_queue(items, _decode_layout(metadata[0]))
        if rendered != source.text:
            diffs.append(
                f"line queue {source.path}: exported content differs from file"
            )
    return diffs


def _render_line_queue(
    items: dict[str, dict[str, object]], header: dict[str, object]
) -> str:
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
        extra = items.get(str(entry.get("id", "")))
        if extra is None:
            continue
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
        task = str(extra.get("task", entry.get("id", "")))
        output.append(" | ".join([task, *fields]) + "\n")
    return "".join(output)


def _verify_database(
    working: Path, expected: ExpectedMigration | None = None
) -> list[str]:
    expected = expected or _expected(working)
    database = working / QUEUE_DATABASE
    if not database.is_file():
        return [
            *(f"missing queue row {key}" for key in expected.queues),
            *(f"missing queue metadata {name}" for name in expected.queue_headers),
            *(
                f"missing line queue metadata {source.path}"
                for source in expected.sources
                if source.kind == "line"
            ),
            *(f"missing plan row {key}" for key in expected.plans),
            *(f"missing task row {key}" for key in expected.tasks),
        ]
    diffs: list[str] = []
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        actual_queues = {
            (row["queue_name"], row["id"]): row
            for row in db.execute("SELECT * FROM queue_items")
        }
        for key in expected.queues.keys() | actual_queues.keys():
            imported = expected.queues.get(key)
            actual = actual_queues.get(key)
            if imported is None or actual is None:
                diffs.append(
                    f"queue row {key}: "
                    f"{'unexpected' if imported is None else 'missing'}"
                )
                continue
            values = {
                "id": imported.id,
                "queue_name": imported.queue_name,
                "plan_dir": imported.plan_dir,
                "findings": imported.findings,
                "owned_files": imported.owned_files,
                "depends_cell": imported.depends_cell,
                "depends_on": json.dumps(imported.depends_on),
                "serialize_with": json.dumps(imported.serialize_with),
                "priority": imported.priority,
                "state": imported.state,
                "planned_at": imported.planned_at,
                "plan_reviewed_at": imported.plan_reviewed_at,
                "build_started_at": imported.build_started_at,
                "build_done_at": imported.build_done_at,
                "merged_at": imported.merged_at,
                "row_order": imported.row_order,
                "role": None,
                "claimed_by": None,
                "claim_expires_at": None,
                "claim_generation": 0,
                "claim_epoch": None,
                "extra": json.dumps(imported.extra or {}, sort_keys=True),
            }
            for column, value in values.items():
                if actual[column] != value:
                    diffs.append(
                        f"queue row {key} column {column}: "
                        f"expected {value!r}, got {actual[column]!r}"
                    )
        diffs.extend(_verify_table_headers(db, expected.queue_headers))
        diffs.extend(_verify_line_queues(working, db, expected.sources))
        actual_plans = {
            row["plan_dir"]: row for row in db.execute("SELECT * FROM plan_state")
        }
        for key in expected.plans.keys() | actual_plans.keys():
            wanted = expected.plans.get(key)
            actual = actual_plans.get(key)
            if wanted is None or actual is None:
                diffs.append(
                    f"plan row {key}: {'unexpected' if wanted is None else 'missing'}"
                )
                continue
            for column, value in wanted.items():
                if actual[column] != value:
                    diffs.append(
                        f"plan row {key} column {column}: "
                        f"expected {value!r}, got {actual[column]!r}"
                    )
        actual_tasks = {
            (row["plan_dir"], row["task_id"]): row
            for row in db.execute("SELECT * FROM task_state")
        }
        for key in expected.tasks.keys() | actual_tasks.keys():
            wanted = expected.tasks.get(key)
            actual = actual_tasks.get(key)
            if wanted is None or actual is None:
                diffs.append(
                    f"task row {key}: {'unexpected' if wanted is None else 'missing'}"
                )
                continue
            for column, value in wanted.items():
                if actual[column] != value:
                    diffs.append(
                        f"task row {key} column {column}: "
                        f"expected {value!r}, got {actual[column]!r}"
                    )
    return diffs


def verify(working: str | Path) -> list[str]:
    """Compare every imported queue and plan/task state field to Markdown."""
    return _verify_database(Path(working))


def _skipped_line_report(source: QueueSource) -> tuple[str, ...]:
    parsed = parse_line_queue(source.text)
    skipped: list[str] = []
    line_number = 0
    for kind, value in parsed.layout:
        raw = str(value) if kind == "raw" else parsed.rows[int(value)].raw
        if kind == "raw" and line_number > 0 and raw.strip():
            skipped.append(f"{source.path}:{line_number + 1}: {raw.rstrip()}")
        line_number += raw.count("\n") or 1
    return tuple(skipped)


def _report_skips(expected: ExpectedMigration) -> tuple[str, ...]:
    unknown = tuple(
        f"{path}: skipped: unknown format" for path in expected.unknown_formats
    )
    task_states = tuple(
        f"{path}: skipped: not a task state document"
        for path in expected.skipped_task_states
    )
    return unknown + task_states


def migrate(
    working: str | Path,
    dry_run: bool = False,
    *,
    timeout: float = 30,
    crash: Callable[[str], None] | None = None,
) -> MigrationReport:
    """Import state under the exclusive mode barrier and flip only after verify."""
    root = Path(working).resolve()
    hit = crash or _checkpoint
    if dry_run:
        expected = _expected(root)
        collision = _collision_error(root, expected)
        if collision is not None:
            raise collision
        return MigrationReport(
            True,
            None,
            tuple(_verify_database(root, expected)),
            _report_skips(expected),
            (),
            tuple(
                line
                for source in expected.sources
                if source.kind == "line"
                for line in _skipped_line_report(source)
            ),
            expected.unknown_formats,
        )
    with barrier(root, timeout=timeout):
        _ensure_legacy_queue_merged(root)
        expected = _expected(root)
        collision = _collision_error(root, expected)
        if collision is not None:
            raise collision
        database = root / QUEUE_DATABASE
        saved = (
            _snapshot(
                database,
                root / ".cache/inbox/backups",
                "inbox-before-markdown-queue-import",
            )
            if database.is_file()
            else None
        )
        if saved is not None:
            hit("backup")
        SQLiteMessages(database)
        # Initialize schema only after the verified pre-migration backup.
        store = SQLiteQueue(database)
        with store._connection() as db:
            configure_store(db)
            db.execute(
                "INSERT INTO queue_store_meta(key,value) "
                "VALUES('store_mode','markdown') "
                "ON CONFLICT(key) DO NOTHING"
            )
        hit("initialized")
        skipped = list(_report_skips(expected))
        for source in expected.sources:
            if source.kind != "table":
                continue
            report = import_queue_md(
                source.path, _queue_name(root, source.path), database=database
            )
            skipped.extend(f"{source.path}: {reason}" for reason in report.skipped)
            hit(f"queue:{source.path}")
        initialize_plan_state(database)
        line_queues: list[str] = []
        skipped_lines: list[str] = []
        for directory in _plan_dirs(root):
            import_plan_dir(root, directory, database=database)
            hit(f"plan:{directory}")
            line_path = directory / "notes" / "queue.md"
            source = next(
                (
                    item
                    for item in expected.sources
                    if item.path == line_path and item.kind == "line"
                ),
                None,
            )
            if source is not None:
                report = import_line_queue(directory, database=database)
                if report.conflicts:
                    raise Conflict(
                        f"line queue import conflict in {source.path}: "
                        + ", ".join(report.conflicts)
                    )
                line_queues.append(str(source.path))
                skipped_lines.extend(_skipped_line_report(source))
                hit(f"line-queue:{source.path}")
        hit("imported")
        differences = _verify_database(root, expected)
        if differences:
            raise Conflict(
                "queue migration verification failed: " + "; ".join(differences[:10])
            )
        hit("verified")
        atomic_write(
            root / QUEUE_VERSION_MARKER,
            f"{QUEUE_MARKER_VERSION}\n".encode("ascii"),
            mode=0o600,
        )
        with store._connection() as db:
            db.execute(
                "INSERT INTO queue_store_meta(key,value) "
                "VALUES('store_mode','sqlite') "
                "ON CONFLICT(key) DO UPDATE SET value='sqlite'"
            )
        hit("flipped")
        return MigrationReport(
            False,
            saved,
            (),
            tuple(skipped),
            tuple(line_queues),
            tuple(skipped_lines),
            expected.unknown_formats,
        )
