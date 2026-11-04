import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from varde_data.errors import Conflict
from varde_data.records.queue import QueueItemInput
from varde_data.role_inbox import open_role_inbox


def _enable_sqlite_queue(root):
    from varde_data.queue_paths import QUEUE_DATABASE
    from varde_data.queue_store import initialize

    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")


def test_message_reads_do_not_consume_unclaimed_work(tmp_path):
    _enable_sqlite_queue(tmp_path)
    inbox = open_role_inbox(tmp_path)
    inbox.add_holder("builder", "holder-1")
    queue = inbox.queue()
    queue.enqueue(QueueItemInput(id="task", plan_dir="plan", role="builder"))

    assert inbox.unread("builder", "holder-1") == ()
    assert queue.get("default", "task").state == "queued"


def test_role_work_claim_is_exclusive_through_inbox_facade(tmp_path):
    _enable_sqlite_queue(tmp_path)
    inbox = open_role_inbox(tmp_path)
    queue = inbox.queue()
    queue.enqueue(QueueItemInput(id="task", plan_dir="plan", role="builder"))

    def claim(worker):
        return inbox.queue().claim("default", worker=worker, role="builder", lease_s=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ("holder-1", "holder-2")))

    winners = [item for item in claims if item is not None]
    assert len(winners) == 1
    assert winners[0].id == "task"


def test_work_lease_expiry_fences_stale_generation(tmp_path):
    _enable_sqlite_queue(tmp_path)
    queue = open_role_inbox(tmp_path).queue()
    queue.enqueue(QueueItemInput(id="task", plan_dir="plan", role="builder"))

    first = queue.claim(
        "default",
        worker="holder-1",
        role="builder",
        lease_s=30,
        now="2030-01-01T00:00:00+00:00",
    )
    assert first is not None
    expired = queue.expire("2030-01-01T00:01:00+00:00")
    assert expired[0].id == "task"
    assert expired[0].claim_generation == first.claim_generation + 1

    second = queue.claim(
        "default",
        worker="holder-2",
        role="builder",
        lease_s=30,
        now="2030-01-01T00:01:00+00:00",
    )
    assert second is not None
    assert second.claim_generation == expired[0].claim_generation + 1
    with pytest.raises(Conflict):
        queue.release(
            "default",
            "task",
            worker="holder-1",
            generation=first.claim_generation,
        )
