from pathlib import Path

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.records.queue import QueueItemInput


def test_finish_claim_enqueues_all_follow_ups_atomically(tmp_path: Path) -> None:
    queue = SQLiteQueue(tmp_path / "queue.sqlite3")
    queue.enqueue(
        QueueItemInput("build", "plan", role="builder", queue_name="roles/plan")
    )
    claimed = queue.claim("roles/plan", worker="builder", lease_s=30)
    assert claimed is not None
    follow_ups = (
        QueueItemInput(
            "build-review-readability",
            "plan",
            role="readability",
            queue_name="roles/plan",
        ),
        QueueItemInput(
            "build-review-accessibility",
            "plan",
            role="accessibility",
            queue_name="roles/plan",
        ),
    )

    finished, enqueued = queue.finish_claim(
        "roles/plan",
        "build",
        worker="builder",
        generation=claimed.claim_generation,
        to_state="done",
        follow_ups=follow_ups,
    )

    assert finished.state == "done"
    assert [item.id for item in enqueued] == [item.id for item in follow_ups]
    assert {item.id for item in queue.list("roles/plan", state="queued")} == {
        item.id for item in follow_ups
    }
