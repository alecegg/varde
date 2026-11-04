from pathlib import Path
from threading import Event, Thread

import pytest
from varde_data.decisions import open_decisions
from varde_data.records.decisions import DecisionProjection
from varde_runner.decisions import DecisionStore


def _projection(decision_id: str) -> DecisionProjection:
    return DecisionProjection(
        source_id=f"source-{decision_id}",
        decision_id=decision_id,
        kind="question",
        title="A question",
        body="Question body",
        context={"type": "question", "question": "What next?"},
        plan_id="plan-1",
        source_agent="agent-1",
    )


def test_facade_matches_repository_and_instances_share_writes(tmp_path: Path) -> None:
    facade_dir = tmp_path / "facade"
    repository_dir = tmp_path / "repository"

    def send(**_kwargs):
        return {"id": "reply-1"}

    facade = DecisionStore(facade_dir, send=send, read_messages=list)
    repository = open_decisions(repository_dir)

    facade.project(_projection("facade-decision"))
    repository.project(_projection("repository-decision"))
    facade_result = facade.submit_answer(
        "facade-decision", "facade-key", "agent-1", "The answer"
    )
    repository_result = DecisionStore(
        repository_dir, send=send, read_messages=list
    ).submit_answer("repository-decision", "repository-key", "agent-1", "The answer")

    facade_decision = facade.get_decision("facade-decision")
    repository_decision = repository.get_decision("repository-decision")
    assert facade_decision is not None and repository_decision is not None
    assert facade_decision["state"] == repository_decision.state == "answered"
    assert facade_decision["kind"] == repository_decision.kind == "question"
    assert facade_decision["context"] == repository_decision.record["context"]
    assert facade_result.status == repository_result.status == "delivered"
    facade_entry = facade.get_entry("facade-key")
    repository_entry = repository.get_entry("repository-key")
    assert facade_entry is not None and repository_entry is not None
    assert facade_entry.body == repository_entry.body
    facade_reply = facade.latest_delivered_reply("facade-decision")
    repository_reply = repository.latest_delivered_reply("repository-decision")
    assert facade_reply is not None and repository_reply is not None
    assert facade_reply.body == repository_reply.body
    assert [row["new_state"] for row in facade.audit_rows()] == [
        row.new_state for row in repository.audit_rows()
    ]

    first = DecisionStore(tmp_path / "shared", send=send, read_messages=list)
    second = DecisionStore(tmp_path / "shared", send=send, read_messages=list)
    first.project(_projection("shared-a"))
    shared_a = second.get_decision("shared-a")
    assert shared_a is not None and shared_a["state"] == "pending"
    second.project(_projection("shared-b"))
    shared_b = first.get_decision("shared-b")
    assert shared_b is not None and shared_b["state"] == "pending"

    facade.close()
    repository.close()
    first.close()
    second.close()


def test_facade_serializes_answer_submissions(tmp_path: Path) -> None:
    send_entered = Event()
    release_send = Event()
    second_started = Event()
    second_finished = Event()
    send_count = 0
    results = []

    def send(**_kwargs):
        nonlocal send_count
        send_count += 1
        send_entered.set()
        assert release_send.wait(timeout=2)
        return {"id": "reply-1"}

    store = DecisionStore(tmp_path, send=send, read_messages=list)
    first = Thread(
        target=lambda: results.append(
            store.submit_answer("serialized", "one-key", "agent", "answer")
        )
    )

    def submit_second() -> None:
        second_started.set()
        results.append(store.submit_answer("serialized", "one-key", "agent", "answer"))
        second_finished.set()

    second = Thread(target=submit_second)
    first.start()
    assert send_entered.wait(timeout=2)
    second.start()
    assert second_started.wait(timeout=2)
    assert not second_finished.wait(timeout=0.05)
    release_send.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive() and not second.is_alive()
    assert second_finished.is_set()
    assert send_count == 1
    assert [result.status for result in results] == ["delivered", "delivered"]
    store.close()


def test_facade_maps_missing_entry_errors_to_key_error(tmp_path: Path) -> None:
    store = DecisionStore(tmp_path, send=lambda **_kwargs: {}, read_messages=list)

    with pytest.raises(KeyError, match="missing-key"):
        store.retry("missing-key")
    with pytest.raises(KeyError, match="missing-entry"):
        store.resolve_permission("missing-entry", success=True)

    store.close()
