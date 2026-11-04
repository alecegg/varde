from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Barrier, Event
from typing import Any

import pytest
from contract.decisions_backends import backend_registry
from varde_data.answer_flow import AnswerFlow
from varde_data.errors import NotFound
from varde_data.records.decisions import DecisionProjection


@pytest.fixture(
    params=list(backend_registry().values()), ids=lambda backend: backend.name
)
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    return request.param.factory(tmp_path)


def project(repo: Any, *, kind: str = "agent_question") -> None:
    repo.project(
        DecisionProjection(
            "source",
            "decision",
            kind,
            "Question",
            "Body",
            {"question": "What?", "type": "question"},
            plan_id="plan",
        )
    )


def test_submit_replay_is_idempotent(repo: Any) -> None:
    project(repo)
    sent: list[dict[str, Any]] = []

    def send(**message: Any) -> dict[str, Any]:
        sent.append(message)
        return {"id": "msg-1"}

    flow = AnswerFlow(repo, send, list)
    first = flow.submit_answer("decision", "key", "agent", "answer")
    second = flow.submit_answer("decision", "key", "agent", "answer")

    assert first.status == "delivered"
    assert second == first
    assert len(sent) == 1


def test_recover_sending_reconciles_without_resending(repo: Any) -> None:
    project(repo)
    answer = repo.submit_answer("decision", "key", "agent", "answer").entry
    repo.transition_entry(answer.entry_id, "sending", "stored", "delivery started")
    sent: list[dict[str, Any]] = []
    flow = AnswerFlow(
        repo,
        lambda **msg: sent.append(msg) or {},
        lambda: [{"id": "msg-1", "notes": answer.notes_path}],
    )

    recovered = flow.recover_sending()

    assert recovered[0].status == "delivered"
    assert recovered[0].delivery_msg_id == "msg-1"
    assert sent == []


def test_retry_after_answer_row_and_note_write_sends_once(repo: Any) -> None:
    project(repo)
    answer = repo.submit_answer("decision", "key", "agent", "answer").entry
    with open(answer.notes_path, "wb") as notes:
        notes.write(answer.body.encode("utf-8"))
    sent: list[dict[str, Any]] = []
    flow = AnswerFlow(repo, lambda **msg: sent.append(msg) or {"id": "msg-1"}, list)

    result = flow.retry("key")

    assert result.status == "delivered"
    assert len(sent) == 1


def test_notes_write_failure_then_retry(
    repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    project(repo)
    flow = AnswerFlow(repo, lambda **msg: {"id": "msg-1"}, list)
    original_write = repo.write_answer_note
    monkeypatch.setattr(
        repo,
        "write_answer_note",
        lambda entry_id, body: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = flow.submit_answer("decision", "key", "agent", "answer")
    assert result.status == "failed"
    monkeypatch.setattr(repo, "write_answer_note", original_write)
    assert flow.retry("key").status == "delivered"


def test_writeback_failure_retries_at_most_three(repo: Any) -> None:
    project(repo)
    failures = 0

    def write_back(*args: str) -> None:
        nonlocal failures
        failures += 1
        raise RuntimeError("not ready")

    flow = AnswerFlow(repo, lambda **msg: {"id": "msg-1"}, list, write_back)
    assert (
        flow.submit_answer("decision", "key", "agent", "answer").status == "delivered"
    )
    for _ in range(4):
        flow.retry_plan_writebacks()
    assert failures == 3


def test_send_then_transition_crash_recovers(repo: Any) -> None:
    project(repo)
    sent_messages: list[dict[str, Any]] = []
    flow = AnswerFlow(
        repo,
        lambda **msg: sent_messages.append(msg) or {"id": "msg-1"},
        lambda: [{"id": "msg-1", "notes": sent_messages[0]["notes"]}],
    )
    original = repo.transition_entry
    failed_once = False

    def fail_delivery_transition(*args: Any, **kwargs: Any) -> bool:
        nonlocal failed_once
        if args[1] == "delivered" and not failed_once:
            failed_once = True
            raise RuntimeError("crash after send")
        return original(*args, **kwargs)

    repo.transition_entry = fail_delivery_transition  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="crash after send"):
        flow.submit_answer("decision", "key", "agent", "answer")
    repo.transition_entry = original  # type: ignore[method-assign]
    assert flow.recover_sending()[0].status == "delivered"
    assert len(sent_messages) == 1


def test_same_key_with_different_answer_conflicts(repo: Any) -> None:
    project(repo)
    flow = AnswerFlow(repo, lambda **msg: {"id": "msg"}, list)
    flow.submit_answer("decision", "key", "agent", "answer")
    result = flow.submit_answer("decision", "key", "agent", "different")
    assert result.status == "idempotency_conflict"
    assert result.status_code == 409


def test_new_key_after_answer_maps_already_answered(repo: Any) -> None:
    project(repo)
    flow = AnswerFlow(repo, lambda **msg: {"id": "msg"}, list)
    flow.submit_answer("decision", "key", "agent", "answer")

    result = flow.submit_answer("decision", "other-key", "agent", "other")

    assert result.status == "already_answered"
    assert result.status_code == 409


def test_project_records_each_pending_write_but_skips_permissions(repo: Any) -> None:
    recorded: list[tuple[str, dict[str, Any]]] = []
    flow = AnswerFlow(
        repo,
        lambda **msg: {"id": "msg"},
        list,
        recorder=lambda event, decision: recorded.append((event, decision)),
    )
    projection = DecisionProjection(
        "source", "decision", "question", "Title", "Body", {}
    )

    assert flow.project(projection)
    assert flow.project(
        DecisionProjection("source-2", "decision", "question", "Updated", "", {})
    )
    assert [event for event, _ in recorded] == ["created", "created"]

    permission = DecisionProjection(
        "permission-source", "permission", "permission", "Title", "Body", {}
    )
    assert flow.project(permission)
    assert [event for event, _ in recorded] == ["created", "created"]


def test_permission_resolution_missing_entry_raises_not_found(repo: Any) -> None:
    with pytest.raises(NotFound):
        repo.resolve_permission("missing", success=True)


def test_concurrent_retry_claims_entry_once(repo: Any) -> None:
    project(repo)
    answer = repo.submit_answer("decision", "key", "agent", "answer").entry
    repo.transition_entry(answer.entry_id, "failed", "stored", "send failed")
    callers = Barrier(2)
    send_started = Event()
    finish_send = Event()
    sent: list[str] = []

    def read_messages() -> list[dict[str, Any]]:
        callers.wait()
        return []

    def send(**message: Any) -> dict[str, Any]:
        sent.append(message["text"])
        send_started.set()
        assert finish_send.wait(timeout=5)
        return {"id": "msg-1"}

    flow = AnswerFlow(
        repo,
        send,
        read_messages,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(flow.retry, "key") for _ in range(2)]
        assert send_started.wait(timeout=5)
        # Let the losing retry observe the sending claim before delivery finishes.
        completed, pending = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
        assert len(completed) == 1
        results = [future.result() for future in completed]
        assert len(results) == 1
        assert results[0].status == "sending"
        finish_send.set()
        results.extend(future.result(timeout=5) for future in pending)
    assert len(sent) == 1
    assert {result.status for result in results} == {"sending", "delivered"}
    assert repo.get_entry("key").status == "delivered"


def test_recovery_skips_read_and_does_not_start_writeback(repo: Any) -> None:
    project(repo)
    reads = 0
    writes: list[str] = []

    def read() -> list[dict[str, Any]]:
        nonlocal reads
        reads += 1
        return []

    flow = AnswerFlow(
        repo, lambda **msg: {}, read, lambda *args: writes.append("write")
    )
    assert flow.recover_sending() == []
    assert reads == 0
    answer = repo.submit_answer("decision", "key", "agent", "answer").entry
    repo.transition_entry(answer.entry_id, "sending", "stored", "delivery started")
    flow.recover_sending()
    assert writes == []


@pytest.mark.parametrize("body", ["APPROVED", "APPROVED:yes"])
def test_approval_answer_writes_back(body: str, repo: Any) -> None:
    repo.project(
        DecisionProjection(
            "source",
            "approval",
            "approval",
            "Approval",
            "Body",
            {"type": "approval", "question": "Approve?"},
            plan_id="plan",
        )
    )
    writes: list[tuple[str, str, str]] = []
    flow = AnswerFlow(
        repo,
        lambda **msg: {"id": "message"},
        list,
        lambda *args: writes.append(args),
    )
    assert flow.submit_answer("approval", "key", "agent", body).status == "delivered"
    assert writes == [("plan", "Approve?", body)]


def test_answered_recorder_event_and_permission_submit(repo: Any) -> None:
    project(repo)
    events: list[str] = []
    sent: list[dict[str, Any]] = []
    flow = AnswerFlow(
        repo,
        lambda **message: sent.append(message) or {"id": "message"},
        list,
        recorder=lambda event, payload: events.append(event),
    )
    flow.submit_answer("decision", "key", "agent", "answer")
    assert events == ["answered"]

    repo.project(DecisionProjection("s", "permission", "permission", "t", "b", {}))
    permission_result = flow.submit_answer(
        "permission", "permission-key", "agent", "yes"
    )
    assert permission_result.status == "stored"
    assert len(sent) == 1


def test_recorder_failure_does_not_fail_delivery(repo: Any) -> None:
    project(repo)

    def recorder(event: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("recorder unavailable")

    flow = AnswerFlow(
        repo, lambda **message: {"id": "message"}, list, recorder=recorder
    )
    assert (
        flow.submit_answer("decision", "key", "agent", "answer").status == "delivered"
    )


def test_sqlite_flow_matches_reference_idempotency_golden(tmp_path: Path) -> None:
    from varde_data.backends.sqlite.decisions import SqliteDecisions

    repo = SqliteDecisions(tmp_path)
    repo.project(
        DecisionProjection(
            "golden",
            "golden",
            "question",
            "Title",
            "Body",
            {"type": "question", "question": "Q"},
        )
    )
    sent: list[dict[str, Any]] = []
    flow = AnswerFlow(
        repo,
        lambda **message: sent.append(message) or {"id": "delivery-1"},
        list,
    )
    first = flow.submit_answer("golden", "golden-key", "agent", "answer")
    replay = flow.submit_answer("golden", "golden-key", "agent", "answer")
    conflict = flow.submit_answer("golden", "golden-key", "agent", "different")
    reference = json.loads(
        (
            Path(__file__).parents[2] / "data/tests/golden/decisions/scenarios.json"
        ).read_text(encoding="utf-8")
    )["idempotency"]
    assert [first.status, replay.status, conflict.status] == [
        row["result"]["status"] for row in reference
    ]
    assert [row.reason for row in repo.audit_rows("golden")] == [
        "answer stored",
        "delivery started",
        "answer delivered",
    ]
    assert len(sent) == 1
    repo.close()
