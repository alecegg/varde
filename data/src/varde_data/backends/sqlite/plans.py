"""SQLite-backed plan reads with file-backed writes."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from varde_core.frontmatter import parse
from varde_data.backends.files.plans import KNOWN, FilesPlans
from varde_data.backends.sqlite.plans_index import SqlitePlansIndex
from varde_data.errors import NotFound
from varde_data.records.plans import PlanRecord, ReadResult, TaskRecord
from varde_data.repos.plans import resolve_plan_head
from varde_data.version import Version

logger = logging.getLogger(__name__)


class SqlitePlans:
    """Read an indexed snapshot and delegate mutations to Markdown files."""

    def __init__(self, working: Path) -> None:
        self.working = Path(working)
        self._index = SqlitePlansIndex(self.working)
        self._writer = FilesPlans(self.working)

    def refresh(self) -> int:
        """Refresh the derived index from the source tree."""
        return self._index.refresh()

    def generation(self) -> int:
        return self._index.generation()

    def plan_rows(self) -> list[dict[str, object]]:
        return self._index.plan_rows()

    def task_rows(self, plan_path: str | None = None) -> list[dict[str, object]]:
        return self._index.task_rows(plan_path)

    def review_rows(self) -> list[dict[str, object]]:
        return self._index.review_rows()

    def task_note_rows(self) -> list[dict[str, object]]:
        return self._index.task_note_rows()

    def now_line_rows(self) -> list[dict[str, object]]:
        return self._index.now_line_rows()

    def invalid_rows(self) -> list[dict[str, object]]:
        return self._index.invalid_rows()

    def activity_rows(self) -> list[dict[str, object]]:
        return self._index.activity_rows()

    def status_rows(self) -> dict[str, list[dict[str, object]]]:
        return self._index.status_rows()

    def watch_rows(self) -> dict[str, list[dict[str, object]]]:
        return self._index.watch_rows()

    def list(
        self, *, include_archived: bool = False, include_tasks: bool = True
    ) -> ReadResult:
        with self._index._connection() as db:
            plans = db.execute(
                "SELECT * FROM plans WHERE archived=0 OR ? ORDER BY path",
                (int(include_archived),),
            ).fetchall()
            tasks = db.execute(
                "SELECT * FROM tasks WHERE archived=0 OR ? ORDER BY path",
                (int(include_archived),),
            ).fetchall()
            reviews = {
                row["plan_path"]: row["verdict"]
                for row in db.execute("SELECT plan_path,verdict FROM reviews")
            }
            invalid = db.execute(
                "SELECT path,kind,plan_path FROM invalid_artifacts "
                "WHERE archived=0 OR ?",
                (int(include_archived),),
            ).fetchall()
        tasks_by_plan: dict[str, list[TaskRecord]] = {}
        if include_tasks:
            for row in tasks:
                task = _task_record(row)
                tasks_by_plan.setdefault(str(row["plan_path"]), []).append(task)
        records = [_plan_record(row) for row in plans]
        plan_paths = {record.path for record in records}
        results = []
        for record in records:
            if record.artifact_type != "plan":
                results.append(record)
                continue
            attached = (
                tuple(tasks_by_plan.get(record.path, ())) if include_tasks else ()
            )
            results.append(
                replace(
                    record,
                    tasks=attached,
                    skipped_tasks=record.skipped_tasks if include_tasks else 0,
                    review_verdict=reviews.get(record.path),
                )
            )
        results.extend(
            _task_as_plan(row) for row in tasks if _standalone(row, plan_paths)
        )
        results.sort(key=lambda record: record.path)
        skipped = sum(
            row["kind"] == "document"
            or (
                row["kind"] == "task"
                and row["plan_path"] not in plan_paths
                and Path(str(row["path"])).name in {"plan.md", "task.md"}
            )
            for row in invalid
        )
        return ReadResult(tuple(results), skipped)

    def get(self, plan_ref: str, *, include_archived: bool = False) -> PlanRecord:
        with self._index._connection() as db:
            plan_rows = db.execute(
                "SELECT path,frontmatter_json,frontmatter_json_exact,"
                "CASE WHEN frontmatter_json_exact=0 THEN raw END AS raw "
                "FROM plans WHERE archived=0 OR ?",
                (int(include_archived),),
            ).fetchall()
            task_rows = db.execute(
                "SELECT path,plan_path,frontmatter_json,frontmatter_json_exact,"
                "CASE WHEN frontmatter_json_exact=0 THEN raw END AS raw "
                "FROM tasks WHERE archived=0 OR ?",
                (int(include_archived),),
            ).fetchall()
        heads = tuple(
            (Path(str(row["path"])), _fields_from_row(row)) for row in plan_rows
        )
        plan_paths = {str(row["path"]) for row in plan_rows}
        heads += tuple(
            (Path(str(row["path"])), _fields_from_row(row))
            for row in task_rows
            if _standalone(row, plan_paths)
        )
        path = resolve_plan_head(plan_ref, heads)
        if path is None:
            raise NotFound(f"plan {plan_ref!r} not found")
        return self.get_by_path(str(path))

    def get_by_path(self, path: str) -> PlanRecord:
        absolute = os.path.abspath(path)
        with self._index._connection() as db:
            row = db.execute(
                "SELECT * FROM plans WHERE path IN (?,?)", (path, absolute)
            ).fetchone()
            if row is not None:
                record = _plan_record(row)
                if record.artifact_type != "plan":
                    return record
                review = db.execute(
                    "SELECT verdict FROM reviews WHERE plan_path=?", (record.path,)
                ).fetchone()
                tasks = db.execute(
                    "SELECT * FROM tasks WHERE plan_path=? ORDER BY path",
                    (record.path,),
                ).fetchall()
                return replace(
                    record,
                    review_verdict=review["verdict"] if review else None,
                    tasks=tuple(_task_record(task) for task in tasks),
                )
            task = db.execute(
                "SELECT * FROM tasks WHERE path IN (?,?)", (path, absolute)
            ).fetchone()
        if task is None:
            raise NotFound(f"plan file {path!r} not found")
        return _task_as_plan(task)

    def records_by_paths(self, paths: tuple[str, ...]) -> dict[str, PlanRecord]:
        """Read related plan records and task rows in one SQLite snapshot."""
        if not paths:
            return {}
        with self._index._connection() as db:
            db.execute("BEGIN")
            plans = []
            tasks = []
            for path in paths:
                absolute = os.path.abspath(path)
                plans.extend(
                    db.execute(
                        "SELECT * FROM plans WHERE path IN (?,?)", (path, absolute)
                    ).fetchall()
                )
                tasks.extend(
                    db.execute(
                        "SELECT * FROM tasks WHERE plan_path=? ORDER BY path", (path,)
                    ).fetchall()
                )
            reviews = {
                row["plan_path"]: row["verdict"]
                for row in db.execute("SELECT plan_path,verdict FROM reviews")
            }
        tasks_by_plan: dict[str, list[TaskRecord]] = {}
        for row in tasks:
            tasks_by_plan.setdefault(str(row["plan_path"]), []).append(
                _task_record(row)
            )
        records = {}
        for row in plans:
            record = _plan_record(row)
            if record.artifact_type == "plan":
                record = replace(
                    record,
                    tasks=tuple(tasks_by_plan.get(record.path, ())),
                    review_verdict=reviews.get(record.path),
                )
            records[record.path] = record
        return records

    def owner_lookup(
        self, owner: str, *, include_archived: bool = False
    ) -> tuple[PlanRecord, ...]:
        with self._index._connection() as db:
            rows = db.execute(
                "SELECT * FROM plans WHERE artifact_type='plan' AND owner=? "
                "AND (archived=0 OR ?) ORDER BY path",
                (owner, int(include_archived)),
            ).fetchall()
        return tuple(replace(_plan_record(row), skipped_tasks=0) for row in rows)

    def version(self) -> Version:
        with self._index._connection() as db:
            generation = int(db.execute("SELECT generation FROM meta").fetchone()[0])
        return Version(generation)

    def set_task_status(
        self,
        task: TaskRecord | PlanRecord,
        status: str,
        *,
        status_at: str,
        transitions: Mapping[str, frozenset[str]],
    ) -> TaskRecord:
        updated = self._writer.set_task_status(
            task, status, status_at=status_at, transitions=transitions
        )
        self._refresh_after_write()
        return updated

    def set_owner(self, plan: PlanRecord, owner: str | None) -> PlanRecord:
        updated = self._writer.set_owner(plan, owner)
        self._refresh_after_write()
        return updated

    def set_assigned_to(self, plan: PlanRecord, value: str | None) -> PlanRecord:
        updated = self._writer.set_assigned_to(plan, value)
        self._refresh_after_write()
        return updated

    def set_merge_approved_at(self, plan: PlanRecord, value: str) -> PlanRecord:
        updated = self._writer.set_merge_approved_at(plan, value)
        self._refresh_after_write()
        return updated

    def set_plan_status(self, plan: PlanRecord, status: str) -> PlanRecord:
        updated = self._writer.set_plan_status(plan, status)
        self._refresh_after_write()
        return updated

    def replace_body(self, plan: PlanRecord, body: bytes) -> PlanRecord:
        updated = self._writer.replace_body(plan, body)
        self._refresh_after_write()
        return updated

    def _refresh_after_write(self) -> None:
        try:
            self.refresh()
        except Exception:
            logger.exception("Plan write succeeded, but index refresh failed")


def _plan_record(row: sqlite3.Row) -> PlanRecord:
    raw = bytes(row["raw"])
    fields = _fields_from_row(row)
    extra = {key: value for key, value in fields.items() if key not in KNOWN}
    return PlanRecord(
        str(row["id"]),
        fields,
        raw,
        int(row["mtime_ns"]) / 1_000_000_000,
        str(row["path"]),
        archived=bool(row["archived"]),
        artifact_type=str(row["artifact_type"]),
        skipped_tasks=int(row["skipped_tasks"]),
        extra=extra,
    )


def _task_record(row: sqlite3.Row) -> TaskRecord:
    raw = bytes(row["raw"])
    fields = _fields_from_row(row)
    extra = {key: value for key, value in fields.items() if key not in KNOWN}
    return TaskRecord(
        str(row["id"]),
        fields,
        raw,
        int(row["mtime_ns"]) / 1_000_000_000,
        str(row["path"]),
        extra,
    )


def _task_as_plan(row: sqlite3.Row) -> PlanRecord:
    task = _task_record(row)
    return PlanRecord(
        task.id,
        task.fields,
        task.raw,
        task.mtime,
        task.path,
        archived=bool(row["archived"]),
        artifact_type="task",
        extra=task.extra,
    )


def _standalone(row: sqlite3.Row, plan_paths: set[str]) -> bool:
    path = Path(str(row["path"]))
    return (
        path.name in {"plan.md", "task.md"} and str(row["plan_path"]) not in plan_paths
    )


def _fields_from_row(row: sqlite3.Row) -> dict[str, Any]:
    if row["frontmatter_json_exact"]:
        return cast("dict[str, Any]", json.loads(str(row["frontmatter_json"])))
    raw = bytes(row["raw"])
    fields, _ = parse(raw.replace(b"\r\n", b"\n"))
    return fields
