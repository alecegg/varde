"""Compare-and-swap writers for plan Markdown records."""

from __future__ import annotations

import os
import stat
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from varde_core.frontmatter import parse
from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.frontmatter_patch import has_key_line, patch_fields, replace_body
from varde_data.locking import atomic_write, file_lock
from varde_data.records.plans import PlanRecord, TaskRecord

LOCK_TIMEOUT = 5
Record = PlanRecord | TaskRecord


class PlansWriter(ABC):
    """Writer methods shared by file and in-memory plan repositories."""

    def set_task_status(
        self,
        task: TaskRecord | PlanRecord,
        status: str,
        *,
        status_at: str,
        transitions: Mapping[str, frozenset[str]],
    ) -> TaskRecord:
        if isinstance(task, PlanRecord) and task.artifact_type != "task":
            raise Invalid("record is not a task")

        def update(raw: bytes) -> bytes:
            fields = _parse_fields(raw)
            old = fields.get("status", "todo")
            if not isinstance(old, str) or status not in transitions.get(
                old, frozenset()
            ):
                raise Invalid(
                    f"task status cannot transition from {old!r} to {status!r}"
                )
            return patch_fields(
                raw, set_fields={"status": status, "status_at": status_at}
            )

        return cast("TaskRecord", self._mutate(task, update, task=True))

    def set_owner(self, plan: PlanRecord, owner: str | None) -> PlanRecord:
        return cast(
            "PlanRecord",
            self._patch(
                plan,
                {"owner": owner} if owner is not None else {},
                ("owner",) if owner is None else (),
            ),
        )

    def set_assigned_to(self, plan: PlanRecord, value: str | None) -> PlanRecord:
        return cast(
            "PlanRecord",
            self._patch(
                plan,
                {"assigned_to": value} if value is not None else {},
                ("assigned_to",) if value is None else (),
            ),
        )

    def set_merge_approved_at(self, plan: PlanRecord, value: str) -> PlanRecord:
        _require_plan(plan)

        def update(raw: bytes) -> bytes:
            if has_key_line(raw, "merge_approved_at"):
                return raw
            return patch_fields(raw, set_fields={"merge_approved_at": value})

        return cast("PlanRecord", self._mutate(plan, update, task=False))

    def set_plan_status(self, plan: PlanRecord, status: str) -> PlanRecord:
        return cast("PlanRecord", self._patch(plan, {"status": status}))

    def replace_body(self, plan: PlanRecord, body: bytes) -> PlanRecord:
        _require_plan(plan)
        return cast(
            "PlanRecord",
            self._mutate(plan, lambda raw: replace_body(raw, body), task=False),
        )

    def _patch(
        self, expected: PlanRecord, fields: dict[str, str], remove: tuple[str, ...] = ()
    ) -> Record:
        _require_plan(expected)
        return self._mutate(
            expected,
            lambda raw: patch_fields(raw, set_fields=fields, remove_fields=remove),
            task=False,
        )

    @abstractmethod
    def _mutate(
        self, expected: Record, update: Callable[[bytes], bytes], *, task: bool
    ) -> Record:
        """Apply an update using the backend's lock and raw-byte storage."""
        raise NotImplementedError


class FilePlansWriter(PlansWriter):
    """File-backed compare-and-swap implementation for plan writers."""

    def _mutate(
        self, expected: Record, update: Callable[[bytes], bytes], *, task: bool
    ) -> Record:
        path = Path(expected.path)
        directory = _plan_directory(path)
        with file_lock(directory / ".plan.lock", timeout=LOCK_TIMEOUT):
            try:
                current = path.read_bytes()
                mode = stat.S_IMODE(path.stat().st_mode)
            except OSError as exc:
                raise NotFound(f"plan file {expected.path!r} not found") from exc
            if current != expected.raw:
                raise Conflict("plan content changed")
            updated = _apply_update(update, current)
            if updated != current:
                _replace_if_unchanged(path, current, updated, mode)
            try:
                stored = path.read_bytes()
                modified = path.stat().st_mtime
                return _record_from_bytes(stored, expected, task=task, mtime=modified)
            except (OSError, ValueError) as exc:
                raise Invalid(str(exc)) from exc


def _require_plan(record: PlanRecord) -> None:
    if record.artifact_type != "plan":
        raise Invalid("record is not a plan")


def _apply_update(update: Callable[[bytes], bytes], raw: bytes) -> bytes:
    try:
        return update(raw)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc


def _record_from_bytes(
    raw: bytes, source: Record, *, task: bool, mtime: float
) -> Record:
    try:
        fields = _parse_fields(raw)
    except ValueError as exc:
        raise Invalid(str(exc)) from exc
    extra = _extra_fields(fields)
    if task:
        return TaskRecord(source.id, fields, raw, mtime, source.path, extra)
    if not isinstance(source, PlanRecord):
        raise Invalid("record is not a plan")
    return PlanRecord(
        source.id,
        fields,
        raw,
        mtime,
        source.path,
        archived=source.archived,
        artifact_type=source.artifact_type,
        extra=extra,
    )


def _parse_fields(raw: bytes) -> dict[str, object]:
    fields, _ = parse(raw.replace(b"\r\n", b"\n"))
    return fields


def _extra_fields(fields: dict[str, object]) -> dict[str, object]:
    # Local import avoids plans.py <-> plans_write.py initialization recursion.
    from varde_data.backends.files.plans import KNOWN

    return {key: value for key, value in fields.items() if key not in KNOWN}


def _plan_directory(path: Path) -> Path:
    if path.name == "plan.md":
        return path.parent
    for directory in path.parents:
        if (directory / "plan.md").is_file():
            return directory
    return path.parent


def _replace_if_unchanged(
    path: Path, expected: bytes, updated: bytes, mode: int
) -> None:
    """Stage, compare, and replace; a final hand edit can still race the replace.

    Hand edits do not take the plan lock, so edits between the final read and
    ``os.replace`` may be overwritten despite the compare immediately beforehand.
    """
    staged = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        atomic_write(staged, updated, mode=mode)
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise NotFound(f"plan file {str(path)!r} not found") from exc
        if current != expected:
            raise Conflict("plan content changed")
        os.replace(staged, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        staged.unlink(missing_ok=True)
