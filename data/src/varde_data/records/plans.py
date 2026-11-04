"""Tolerant plan and task records returned by plan readers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskRecord:
    id: str
    fields: dict[str, Any]
    raw: bytes
    mtime: float
    path: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanRecord:
    id: str
    fields: dict[str, Any]
    raw: bytes
    mtime: float
    path: str
    tasks: tuple[TaskRecord, ...] = ()
    skipped_tasks: int = 0
    review_verdict: str | None = None
    archived: bool = False
    artifact_type: str = "plan"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str | None:
        value = self.fields.get("status")
        return value if isinstance(value, str) else None

    @property
    def title(self) -> str | None:
        value = self.fields.get("title")
        return value if isinstance(value, str) else None

    @property
    def owner(self) -> str | None:
        value = self.fields.get("owner")
        return value if isinstance(value, str) else None

    @property
    def assigned_to(self) -> str | None:
        value = self.fields.get("assigned_to")
        return value if isinstance(value, str) else None

    @property
    def depends_on(self) -> tuple[str, ...]:
        value = self.fields.get("depends_on")
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, str))
        return ()


@dataclass(frozen=True)
class ReadResult:
    records: tuple[PlanRecord, ...]
    skipped: int = 0
