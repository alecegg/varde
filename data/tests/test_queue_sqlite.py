from pathlib import Path

import pytest
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.errors import Conflict
from varde_data.records.queue import QueueItemInput


def test_enqueue_is_idempotent_and_preserves_extra(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    item = QueueItemInput("one", "plan", queue_name="test", extra={"new": "value"})
    first = repo.enqueue(item)

    assert repo.enqueue(item) == first
    assert repo.get("test", "one").extra == {"new": "value"}
    assert len(repo.events("one")) == 1


def test_transition_compare_and_swap_and_events(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "plan", queue_name="test"))

    reviewed = repo.transition(
        "test", "one", "in_review", actor="worker", expect_state="queued"
    )
    assert reviewed.plan_reviewed_at is not None
    assert reviewed.build_done_at is not None
    assert (
        repo.transition("test", "one", "in_review", actor="worker").plan_reviewed_at
        == reviewed.plan_reviewed_at
    )
    with pytest.raises(Conflict):
        repo.transition("test", "one", "merged", actor="worker", expect_state="queued")

    events = repo.events("one")
    assert [event.kind for event in events] == ["enqueue", "transition", "transition"]
    assert events[1].from_state == "queued" and events[1].to_state == "in_review"


def test_queue_contract(tmp_path: Path) -> None:
    """Run shared behavior checks as the SQLite backend grows its lease API."""
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    # Shared base contract's claim/release portion is supplied by task 04.
    assert (
        repo.enqueue(QueueItemInput("one", "plan", queue_name="contract")).state
        == "queued"
    )
