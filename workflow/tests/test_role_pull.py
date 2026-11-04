from __future__ import annotations

import multiprocessing
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_data.errors import Conflict
from varde_data.queue import open_queue, open_slots
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_workflow.role_pull import finish, pull, release, renew
from varde_workflow.role_queue_budget import BudgetLimits, ResourceSnapshot

NOW = datetime(2030, 1, 1, tzinfo=UTC)
LIMITS = BudgetLimits({}, 1000, 100, 100, 24)


def _repos(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    return open_queue(root), open_slots(root)


def _setup(root: Path, count: int = 2) -> None:
    queue, slots = _repos(root)
    for index in range(count):
        slot = f"slot-{index}"
        slots.register(
            slot,
            plan_id="plan",
            role="builder",
            agent_ref=f"agent-{index}",
            lease_s=60,
        )
    for index in range(count):
        queue.enqueue(
            QueueItemInput(
                f"item-{index}",
                "plan",
                role="builder",
                queue_name="roles/plan",
                owned_files=f"src/{index}.py",
            )
        )


def _claim_reviewer_findings_item(queue, slots):
    """Claim a reviewer item that will finish with findings."""
    slots.register(
        "review-slot", plan_id="plan", role="reviewer", agent_ref="review-agent"
    )
    queue.enqueue(
        QueueItemInput(
            "plan-review",
            "plan",
            role="reviewer",
            queue_name="roles/plan",
            owned_files="src/a.py",
        )
    )
    claimed = pull(
        queue,
        slots,
        queue_name="roles/plan",
        role="reviewer",
        slot_id="review-slot",
        epoch=1,
        lease_s=60,
        snapshot=_snapshot(),
        limits=LIMITS,
        now=NOW,
    )
    assert claimed.item is not None
    return claimed.item


def _pull_worker(root: str, slot: str, start, output) -> None:
    queue, slots = _repos(Path(root))
    start.wait(timeout=10)
    result = pull(
        queue,
        slots,
        queue_name="roles/plan",
        role="builder",
        slot_id=slot,
        epoch=1,
        lease_s=60,
        snapshot=_snapshot(),
        limits=LIMITS,
        now=NOW,
    )
    output.put(result.item.id if result.item else None)


def _snapshot(**changes) -> ResourceSnapshot:
    values = {
        "taken_at": NOW,
        "providers": {},
        "rss_mb": 0,
        "cpu_pct": 0,
        "processes": 0,
        "live_workers": 0,
    }
    values.update(changes)
    return ResourceSnapshot(**values)


def test_concurrent_pulls_claim_disjoint_items(tmp_path: Path) -> None:
    _setup(tmp_path)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(
            target=_pull_worker,
            args=(str(tmp_path), f"slot-{index}", start, output),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    claimed = [output.get(timeout=2) for _ in processes]
    assert set(claimed) == {"item-0", "item-1"}


def test_stale_epoch_is_rejected(tmp_path: Path) -> None:
    queue, slots = _repos(tmp_path)
    slots.register("slot", plan_id="plan", role="builder", agent_ref="agent")
    slots.replace("slot", new_agent_ref="next")

    with pytest.raises(Conflict, match="epoch or state is stale"):
        pull(
            queue,
            slots,
            queue_name="roles/plan",
            role="builder",
            slot_id="slot",
            epoch=1,
            lease_s=60,
            snapshot=_snapshot(),
            limits=LIMITS,
            now=NOW,
        )


def test_budget_block_does_not_claim(tmp_path: Path) -> None:
    _setup(tmp_path, 1)
    queue, slots = _repos(tmp_path)
    blocked = pull(
        queue,
        slots,
        queue_name="roles/plan",
        role="builder",
        slot_id="slot-0",
        epoch=1,
        lease_s=60,
        snapshot=_snapshot(rss_mb=2000),
        limits=LIMITS,
        now=NOW,
    )
    assert blocked.item is None
    assert blocked.reason == "rss_mb_max"
    assert queue.get("roles/plan", "item-0").state == "queued"


def test_no_independent_item_reports_reason(tmp_path: Path) -> None:
    _setup(tmp_path, 2)
    queue, slots = _repos(tmp_path)
    assert slots.claim("slot-0", epoch=1, queue_name="roles/plan", lease_s=60)
    assert slots.claim("slot-1", epoch=1, queue_name="roles/plan", lease_s=60)
    queue.enqueue(
        QueueItemInput(
            "blocked-item",
            "plan",
            role="builder",
            queue_name="roles/plan",
            depends_on=("item-1",),
        )
    )
    result = pull(
        queue,
        slots,
        queue_name="roles/plan",
        role="builder",
        slot_id="slot-0",
        epoch=1,
        lease_s=60,
        snapshot=_snapshot(),
        limits=LIMITS,
        now=NOW,
    )
    assert result.item is None
    assert result.reason == "no independent item ready"


def test_finish_release_and_renew_are_epoch_fenced(tmp_path: Path) -> None:
    _setup(tmp_path, 1)
    queue, slots = _repos(tmp_path)
    result = pull(
        queue,
        slots,
        queue_name="roles/plan",
        role="builder",
        slot_id="slot-0",
        epoch=1,
        lease_s=60,
        snapshot=_snapshot(),
        limits=LIMITS,
        now=NOW,
    )
    assert result.item is not None
    assert finish(slots, result.item, slot_id="slot-0", epoch=1) == []
    assert queue.list("roles/plan", state="queued") == []
    with pytest.raises(Conflict):
        renew(slots, slot_id="slot-0", epoch=2, lease_s=60)
    with pytest.raises(Conflict):
        release(
            slots,
            queue_name="roles/plan",
            item_id=result.item.id,
            slot_id="slot-0",
            epoch=2,
        )


def test_reviewer_findings_enqueue_builder_fix(
    tmp_path: Path,
) -> None:
    _setup(tmp_path, 0)
    queue, slots = _repos(tmp_path)
    review = _claim_reviewer_findings_item(queue, slots)

    fixes = finish(slots, review, slot_id="review-slot", epoch=1, outcome="findings")

    assert [(item.id, item.role) for item in fixes] == [("plan-review-fix", "builder")]
    assert queue.get("roles/plan", "plan-review").state == "done"
    assert queue.get("roles/plan", "plan-review-fix").state == "queued"


def test_finish_enqueue_failure_rolls_back_claim_completion(tmp_path: Path) -> None:
    _setup(tmp_path, 0)
    queue, slots = _repos(tmp_path)
    review = _claim_reviewer_findings_item(queue, slots)
    broken_item = replace(review, extra={"unserializable": object()})
    with pytest.raises(TypeError):
        finish(slots, broken_item, slot_id="review-slot", epoch=1, outcome="findings")
    assert queue.get("roles/plan", review.id).state == "claimed"
    assert queue.list("roles/plan", state="queued") == []
    fixes = finish(slots, review, slot_id="review-slot", epoch=1, outcome="findings")
    assert [item.role for item in fixes] == ["builder"]
    assert queue.get("roles/plan", review.id).state == "done"


def test_conflicting_follow_up_rolls_back_finish(tmp_path: Path) -> None:
    _setup(tmp_path, 0)
    queue, slots = _repos(tmp_path)
    queue.enqueue(
        QueueItemInput(
            "plan-review-fix", "plan", role="builder", queue_name="roles/plan"
        )
    )
    review = _claim_reviewer_findings_item(queue, slots)

    with pytest.raises(Conflict):
        finish(slots, review, slot_id="review-slot", epoch=1, outcome="findings")

    assert queue.get("roles/plan", review.id).state == "claimed"
    assert {item.id for item in queue.list("roles/plan", state="queued")} == {
        "plan-review-fix"
    }


def test_stale_epoch_finish_does_not_enqueue_follow_up(tmp_path: Path) -> None:
    _setup(tmp_path, 1)
    queue, slots = _repos(tmp_path)
    result = pull(
        queue,
        slots,
        queue_name="roles/plan",
        role="builder",
        slot_id="slot-0",
        epoch=1,
        lease_s=60,
        snapshot=_snapshot(),
        limits=LIMITS,
        now=NOW,
    )
    assert result.item is not None
    slots.replace("slot-0", new_agent_ref="replacement")

    with pytest.raises(Conflict, match="epoch or state is stale"):
        finish(slots, result.item, slot_id="slot-0", epoch=1)

    assert queue.get("roles/plan", result.item.id).state == "claimed"
    assert queue.list("roles/plan", state="queued") == []
