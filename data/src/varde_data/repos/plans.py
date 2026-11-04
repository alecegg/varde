"""Read-only plan repository protocol."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from varde_data.records.plans import PlanRecord, ReadResult, TaskRecord
from varde_data.version import Version


class PlanRepositoryReader(Protocol):
    def list(
        self, *, include_archived: bool = False, include_tasks: bool = True
    ) -> ReadResult: ...

    def get(self, plan_ref: str, *, include_archived: bool = False) -> PlanRecord: ...

    def owner_lookup(
        self, owner: str, *, include_archived: bool = False
    ) -> tuple[PlanRecord, ...]: ...

    def version(self) -> Version: ...

    def get_by_path(self, path: str) -> PlanRecord: ...

    def set_task_status(
        self,
        task: TaskRecord | PlanRecord,
        status: str,
        *,
        status_at: str,
        transitions: Mapping[str, frozenset[str]],
    ) -> TaskRecord: ...

    def set_owner(self, plan: PlanRecord, owner: str | None) -> PlanRecord: ...

    def set_assigned_to(self, plan: PlanRecord, value: str | None) -> PlanRecord: ...

    def set_merge_approved_at(self, plan: PlanRecord, value: str) -> PlanRecord: ...

    def set_plan_status(self, plan: PlanRecord, status: str) -> PlanRecord: ...

    def replace_body(self, plan: PlanRecord, body: bytes) -> PlanRecord: ...


def resolve_plan_ref(
    plan_ref: str, records: tuple[PlanRecord, ...]
) -> PlanRecord | None:
    """Resolve by frontmatter id, directory basename, then date suffix."""
    tiers = (
        tuple(record for record in records if record.fields.get("id") == plan_ref),
        tuple(
            record for record in records if Path(record.path).parent.name == plan_ref
        ),
        tuple(
            record
            for record in records
            if _date_suffix(Path(record.path).parent.name, plan_ref)
        ),
    )
    for matches in tiers:
        if matches:
            if len(matches) > 1:
                from varde_data.errors import Conflict

                raise Conflict(f"plan reference {plan_ref!r} is ambiguous")
            return next(iter(matches))
    return None


def resolve_plan_head(
    plan_ref: str, heads: tuple[tuple[Path, dict[str, object]], ...]
) -> Path | None:
    """Resolve frontmatter heads by id, directory basename, then date suffix."""
    tiers = (
        tuple(item for item in heads if item[1].get("id") == plan_ref),
        tuple(item for item in heads if item[0].parent.name == plan_ref),
        tuple(item for item in heads if _date_suffix(item[0].parent.name, plan_ref)),
    )
    for matches in tiers:
        if matches:
            if len(matches) > 1:
                from varde_data.errors import Conflict

                raise Conflict(f"plan reference {plan_ref!r} is ambiguous")
            return next(iter(matches))[0]
    return None


def _date_suffix(dirname: str, plan_ref: str) -> bool:
    return dirname.endswith(f"-{plan_ref}") and len(dirname) > len(plan_ref) + 1
