"""Thread-safe queue repository used by contract tests."""

import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from varde_data.errors import Conflict, NotFound
from varde_data.records.queue import *
from varde_data.repos.queue import Fence, Ready
from varde_data.version import Version


class MemoryQueue:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[tuple[str, str], QueueItem] = {}
        self._events: list[QueueEvent] = []
        self._plans: dict[str, PlanState] = {}
        self._tasks: dict[tuple[str, str], TaskState] = {}

    def version(self) -> Version:
        """Return a token for the complete in-memory queue state."""
        with self._lock:
            return Version(
                (
                    tuple(sorted(self._items.items())),
                    tuple(self._events),
                    tuple(sorted(self._plans.items())),
                    tuple(sorted(self._tasks.items())),
                )
            )

    def _event(
        self, item: QueueItem, kind: str, actor: str, old: str | None = None
    ) -> None:
        self._events.append(
            QueueEvent(
                len(self._events) + 1,
                item.id,
                datetime.now(UTC).isoformat(),
                actor,
                kind,
                old,
                item.state,
            )
        )

    def enqueue(self, item: QueueItemInput) -> QueueItem:
        key = (item.queue_name, item.id)
        with self._lock:
            if key not in self._items:
                self._items[key] = QueueItem(**item.__dict__)
                self._event(self._items[key], "enqueue", "system")
            return self._items[key]

    def list(
        self,
        queue_name: str | None = None,
        state: str | None = None,
        plan_dir: str | None = None,
    ) -> list[QueueItem]:
        with self._lock:
            rows = [
                x
                for x in self._items.values()
                if (queue_name is None or x.queue_name == queue_name)
                and (state is None or x.state == state)
                and (plan_dir is None or x.plan_dir == plan_dir)
            ]
            return sorted(rows, key=lambda x: (x.priority, x.row_order))

    def get(self, queue_name: str, item_id: str) -> QueueItem:
        try:
            return self._items[(queue_name, item_id)]
        except KeyError as exc:
            raise NotFound(item_id) from exc

    def transition(
        self,
        queue_name: str,
        item_id: str,
        to_state: str,
        *,
        actor: str,
        expect_state: str | None = None,
        expect_generation: int | None = None,
    ) -> QueueItem:
        with self._lock:
            item = self.get(queue_name, item_id)
            if (expect_state is not None and item.state != expect_state) or (
                expect_generation is not None
                and item.claim_generation != expect_generation
            ):
                raise Conflict("queue item changed")
            old = item.state
            fields = {
                "plan_reviewed_at": "in_review",
                "build_started_at": "building",
                "build_done_at": "in_review",
                "merged_at": "merged",
            }
            changes = {
                name: datetime.now(UTC).isoformat()
                for name, val in fields.items()
                if val == to_state and getattr(item, name) is None
            }
            item = replace(item, state=to_state, **changes)
            if to_state in {"merged", "blocked", "cancelled", "queued"}:
                item = replace(item, claimed_by=None, claim_expires_at=None)
            self._items[(queue_name, item_id)] = item
            self._event(item, "transition", actor, old)
            return item

    def _fence(self, fence: Fence | None) -> None:
        if fence:
            fence(None)

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
    ) -> QueueItem | None:
        with self._lock:
            self._fence(fence)
            current = datetime.fromisoformat(now) if now else datetime.now(UTC)
            inflight = (
                self.list(state="claimed")
                + self.list(state="building")
                + self.list(state="in_review")
            )
            for item in self.list(queue_name, "queued"):
                if role is not None and item.role not in {None, role}:
                    continue
                if any(
                    self.get(queue_name, dep).state != "merged"
                    for dep in item.depends_on
                    if (queue_name, dep) in self._items
                ):
                    continue
                if any(
                    any(x.id == serial for x in inflight)
                    for serial in item.serialize_with
                ):
                    continue
                if ready and not ready(item, inflight):
                    continue
                updated = replace(
                    item,
                    state="claimed",
                    claimed_by=worker,
                    claim_expires_at=(current + timedelta(seconds=lease_s)).isoformat(),
                    claim_generation=item.claim_generation + 1,
                    claim_epoch=epoch,
                )
                self._items[(queue_name, item.id)] = updated
                self._event(updated, "claim", worker, item.state)
                return updated
            return None

    def renew(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        lease_s: float,
        fence: Fence | None = None,
    ) -> QueueItem:
        with self._lock:
            self._fence(fence)
            item = self.get(queue_name, item_id)
            if (
                item.claimed_by != worker
                or item.claim_generation != generation
                or item.state not in {"claimed", "building", "in_review"}
            ):
                raise Conflict("lease lost")
            updated = replace(
                item,
                claim_expires_at=(
                    datetime.now(UTC) + timedelta(seconds=lease_s)
                ).isoformat(),
            )
            self._items[(queue_name, item_id)] = updated
            self._event(updated, "renew", worker)
            return updated

    def renew_all(
        self,
        queue_name: str | None,
        *,
        worker: str,
        lease_s: float,
        now: str | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]:
        with self._lock:
            self._fence(fence)
            until = (
                datetime.fromisoformat(now) if now else datetime.now(UTC)
            ) + timedelta(seconds=lease_s)
            result = []
            for item in self.list(queue_name):
                if item.claimed_by == worker and item.state in {
                    "claimed",
                    "building",
                    "in_review",
                }:
                    updated = replace(item, claim_expires_at=until.isoformat())
                    self._items[(item.queue_name, item.id)] = updated
                    self._event(updated, "renew", worker)
                    result.append(updated)
            return result

    def release(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        to_state: str = "queued",
        fence: Fence | None = None,
    ) -> QueueItem:
        with self._lock:
            self._fence(fence)
            item = self.get(queue_name, item_id)
            if item.claimed_by != worker or item.claim_generation != generation:
                raise Conflict("lease lost")
            updated = replace(
                item,
                state=to_state,
                claimed_by=None,
                claim_expires_at=None,
                claim_generation=item.claim_generation + 1,
            )
            self._items[(queue_name, item_id)] = updated
            self._event(updated, "release", worker, item.state)
            return updated

    def expire(
        self,
        now: str | None = None,
        *,
        workers: Sequence[str] | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]:
        with self._lock:
            self._fence(fence)
            stamp = datetime.fromisoformat(now) if now else datetime.now(UTC)
            result = []
            for item in list(self._items.values()):
                if (
                    item.claim_expires_at
                    and item.state in {"claimed", "building", "in_review"}
                    and datetime.fromisoformat(item.claim_expires_at) <= stamp
                    and (workers is None or item.claimed_by in workers)
                ):
                    updated = replace(
                        item,
                        state="queued",
                        claimed_by=None,
                        claim_expires_at=None,
                        claim_generation=item.claim_generation + 1,
                    )
                    self._items[(item.queue_name, item.id)] = updated
                    self._event(updated, "expire", "system", item.state)
                    result.append(updated)
            return result

    def events(self, item_id: str) -> list[QueueEvent]:
        return [x for x in self._events if x.item_id == item_id]

    def cycle_times(self, queue_name: str | None = None) -> list[CycleTime]:
        return [CycleTime(x.id) for x in self.list(queue_name)]

    def set_plan_state(
        self,
        plan_dir: str,
        *,
        status: str,
        status_at: str | None = None,
        owner: str | None = None,
        assigned_to: str | None = None,
        merge_approved_at: str | None = None,
    ) -> PlanState:
        state = PlanState(
            plan_dir, status, status_at, owner, assigned_to, merge_approved_at
        )
        self._plans[plan_dir] = state
        return state

    def set_task_state(
        self, plan_dir: str, task_id: str, status: str, *, actor: str
    ) -> TaskState:
        state = TaskState(plan_dir, task_id, status, datetime.now(UTC).isoformat())
        self._tasks[(plan_dir, task_id)] = state
        return state

    def plan_state(self, plan_dir: str) -> PlanState:
        try:
            return self._plans[plan_dir]
        except KeyError as exc:
            raise NotFound(plan_dir) from exc

    def task_states(self, plan_dir: str) -> list[TaskState]:
        return [x for x in self._tasks.values() if x.plan_dir == plan_dir]
