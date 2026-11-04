"""Backend-neutral queue repository contract."""

import sqlite3
from collections.abc import Callable, Sequence
from typing import Protocol

from varde_data.records.queue import (
    CycleTime,
    PlanState,
    QueueEvent,
    QueueItem,
    QueueItemInput,
    TaskState,
)
from varde_data.version import Version

Fence = Callable[[sqlite3.Connection | None], None]
Ready = Callable[[QueueItem, Sequence[QueueItem]], bool]


class QueueRepository(Protocol):
    def version(self) -> Version: ...
    def enqueue(self, item: QueueItemInput) -> QueueItem: ...
    def list(
        self,
        queue_name: str | None = None,
        state: str | None = None,
        plan_dir: str | None = None,
    ) -> list[QueueItem]: ...
    def get(self, queue_name: str, item_id: str) -> QueueItem: ...
    def transition(
        self,
        queue_name: str,
        item_id: str,
        to_state: str,
        *,
        actor: str,
        expect_state: str | None = None,
        expect_generation: int | None = None,
    ) -> QueueItem: ...
    def claim(  # noqa: PLR0913
        self,
        queue_name: str,
        *,
        worker: str,
        role: str | None = None,
        lease_s: float,
        now: str | None = None,
        ready: Ready | None = None,
        fence: Fence | None = None,
        epoch: int | None = None,
    ) -> QueueItem | None: ...
    def renew_all(
        self,
        queue_name: str | None,
        *,
        worker: str,
        lease_s: float,
        now: str | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]: ...
    def renew(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        lease_s: float,
        fence: Fence | None = None,
    ) -> QueueItem: ...
    def release(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        to_state: str = "queued",
        fence: Fence | None = None,
    ) -> QueueItem: ...
    def expire(
        self,
        now: str | None = None,
        *,
        workers: Sequence[str] | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]: ...
    def events(self, item_id: str) -> list[QueueEvent]: ...
    def cycle_times(self, queue_name: str | None = None) -> list[CycleTime]: ...
    def set_plan_state(
        self,
        plan_dir: str,
        *,
        status: str,
        status_at: str | None = None,
        owner: str | None = None,
        assigned_to: str | None = None,
        merge_approved_at: str | None = None,
    ) -> PlanState: ...
    def set_task_state(
        self, plan_dir: str, task_id: str, status: str, *, actor: str
    ) -> TaskState: ...
    def plan_state(self, plan_dir: str) -> PlanState: ...
    def task_states(self, plan_dir: str) -> list[TaskState]: ...
