from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from decisions_backends import Backend, backend_registry
from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.records.decisions import DecisionProjection
from varde_data.repos.decisions import (
    AlreadyAnswered,
    DecisionRepository,
    IdempotencyConflict,
)


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def backend(request: pytest.FixtureRequest) -> Backend:
    return backend_registry()[request.param]


@pytest.fixture
def repo(backend: Backend, tmp_path: Path) -> DecisionRepository:
    return backend.factory(tmp_path)


def projection(**kwargs) -> DecisionProjection:
    values = {
        "source_id": "source-1",
        "decision_id": "d1",
        "kind": "question",
        "title": "Title",
        "body": "Body",
        "context": {"type": "question", "question": "Q"},
    }
    values.update(kwargs)
    return DecisionProjection(**values)


def test_projection_filters_order_and_non_pending_updates(
    repo: DecisionRepository,
) -> None:
    assert repo.project(projection())
    assert repo.project(projection(source_id="source-2"))
    assert repo.project(projection(decision_id="d2", kind="approval"))
    assert repo.list_decisions() == repo.list_decisions(None, None)
    assert [row.decision_id for row in repo.list_decisions(state="pending")] == [
        "d1",
        "d2",
    ]
    assert [row.decision_id for row in repo.list_decisions(kinds={"approval"})] == [
        "d2"
    ]
    assert [
        row.decision_id for row in repo.list_decisions(kinds={"question", "approval"})
    ] == ["d1", "d2"]
    assert [
        row.decision_id for row in repo.list_decisions("pending", {"question"})
    ] == ["d1"]
    before = repo.get_decision("d1")
    assert repo.dismiss("d1") and not repo.dismiss("d1")
    assert not repo.project(projection(source_id="source-3"))
    assert not repo.dismiss("d1")
    after_project = repo.get_decision("d1")
    assert after_project is not None and before is not None
    assert after_project.source_msg_ids == before.source_msg_ids
    assert repo.restore("d1") and not repo.restore("d1")
    assert not repo.dismiss("missing") and not repo.restore("missing")
    rows = repo.audit_rows("d1")
    assert [(r.seq, r.prior_state, r.new_state, r.reason) for r in rows] == [
        (1, "pending", "dismissed", "dismissed from the dashboard"),
        (2, "dismissed", "pending", "restored from the dashboard"),
    ]


def test_submit_answer_accepts_empty_values_and_typed_conflicts(
    repo: DecisionRepository,
) -> None:
    repo.project(projection())
    repo.project(projection(decision_id="empty-key"))
    assert repo.submit_answer("empty-key", "", "main", "body").entry.status == "stored"
    repo.project(projection(decision_id="empty-recipient"))
    assert (
        repo.submit_answer(
            "empty-recipient", "empty-recipient", "", "body"
        ).entry.status
        == "stored"
    )
    assert (
        repo.submit_answer("", "empty-decision", "main", "body").entry.status
        == "stored"
    )
    submitted = repo.submit_answer("d1", "key", "main", "answer")
    assert submitted.replayed is False
    row = submitted.entry
    replay = repo.submit_answer("d1", "key", "main", "answer")
    assert replay.replayed is True and replay.entry == row
    assert repo.get_entry("key") == row
    with pytest.raises(IdempotencyConflict):
        repo.submit_answer("d1", "key", "other", "answer")
    assert isinstance(IdempotencyConflict(), Conflict)
    with pytest.raises(AlreadyAnswered):
        repo.submit_answer("d1", "new-key", "main", "answer")
    assert isinstance(AlreadyAnswered(), Conflict)
    repo.project(projection(decision_id="dismissed"))
    assert repo.dismiss("dismissed")
    with pytest.raises(AlreadyAnswered):
        repo.submit_answer("dismissed", "dismissed-key", "main", "answer")


def test_unknown_decision_is_created_and_move_missing_or_answered_is_stable(
    repo: DecisionRepository,
) -> None:
    result = repo.submit_answer("unknown", "key", "main", "answer")
    decision = repo.get_decision("unknown")
    assert decision is not None
    assert (
        decision.kind,
        decision.state,
        decision.record,
        decision.source_msg_ids,
    ) == ("agent_question", "answered", {}, [])
    assert not repo.dismiss("unknown")
    assert repo.dismiss("absent") is False
    assert result.entry.decision_id == "unknown"


def test_transition_expected_states_dedupe_and_reply_by_decision(
    repo: DecisionRepository,
) -> None:
    repo.project(projection())
    repo.project(projection(decision_id="d2", source_id="source-2"))
    first = repo.submit_answer("d1", "key1", "same-recipient", "first").entry
    second = repo.submit_answer("d2", "key2", "same-recipient", "second").entry
    assert repo.transition_entry(
        first.entry_id,
        "delivered",
        {"stored", "sending"},
        "sent",
        ["extra"],
        "source-1",
    )
    audit_before_rejected_transition = repo.audit_rows()
    assert not repo.transition_entry(
        first.entry_id, "failed", "stored", "wrong expected"
    )
    assert repo.audit_rows() == audit_before_rejected_transition
    assert not repo.transition_entry("missing", "delivered", "stored", "missing")
    with pytest.raises(Invalid):
        repo.transition_entry("", "delivered", "stored", "missing")
    assert repo.transition_entry(second.entry_id, "sending", "stored", "sending")
    assert repo.transition_entry(
        second.entry_id, "delivered", "sending", "sent", ["reply"], "reply"
    )
    latest_first = repo.latest_delivered_reply("d1")
    assert latest_first is not None and latest_first.body == "first"
    reply = repo.latest_delivered_reply("d2")
    assert reply is not None and (reply.body, reply.sent_at)
    assert repo.latest_delivered_reply("missing") is None
    d1 = repo.get_decision("d1")
    assert d1 is not None and d1.source_msg_ids == ["source-1"]
    assert repo.audit_rows("d1")[-1].msg_ids == ["source-1", "extra"]
    assert repo.audit_rows("d2")[-1].msg_ids == ["source-2", "reply"]
    all_audit = repo.audit_rows()
    assert [row.seq for row in all_audit] == list(range(1, len(all_audit) + 1))
    assert all(row.actor == "user" and row.at for row in all_audit)


def test_permission_resolution_and_status_queries(repo: DecisionRepository) -> None:
    repo.project(DecisionProjection("s", "permission", "permission", "t", "b", {}))
    row = repo.submit_answer("permission", "permission-key", "main", "yes").entry
    assert repo.permission_entry("permission-key")
    assert repo.permission_entry("missing") is False
    assert repo.entries_by_status("stored") == [row]
    assert repo.resolve_permission(row.entry_id, True).status == "delivered"
    assert repo.resolve_permission(row.entry_id, False).status == "delivered"
    assert repo.resolve_permission(row.entry_id, True).status == "delivered"
    latest = repo.latest_delivered_reply("permission")
    assert latest is not None and latest.body == "yes"
    repo.project(DecisionProjection("s2", "permission2", "permission", "t", "b", {}))
    failed = repo.submit_answer("permission2", "old-key", "main", "yes").entry
    assert repo.resolve_permission(failed.entry_id, False).status == "failed"
    assert repo.entries_by_status("failed") == [repo.get_entry("old-key")]
    permission2 = repo.get_decision("permission2")
    assert permission2 is not None and permission2.answer_key is None
    assert (
        repo.submit_answer(
            "permission2", "new-key", "main", "yes"
        ).entry.idempotency_key
        == "new-key"
    )
    with pytest.raises(NotFound):
        repo.resolve_permission("unknown", True)
    repo.project(DecisionProjection("s3", "permission3", "permission", "t", "b", {}))
    failed_again = repo.submit_answer("permission3", "old-key-3", "main", "yes").entry
    repo.resolve_permission(failed_again.entry_id, False)
    permission3 = repo.get_decision("permission3")
    assert permission3 is not None and permission3.state == "pending"
    repo.resolve_permission(failed_again.entry_id, True)
    permission3 = repo.get_decision("permission3")
    assert permission3 is not None
    assert (permission3.state, permission3.answer_key) == ("answered", "old-key-3")


def test_writeback_candidates_require_failures_and_respect_cap(
    repo: DecisionRepository,
) -> None:
    for decision_id, body, context in [
        ("q", "answer", {"type": "question", "question": "Q"}),
        ("approved", "APPROVED", {"type": "approval", "question": "Q"}),
        ("approved-prefix", "APPROVED:x", {"type": "approval", "question": "Q"}),
        ("rejected", "NO", {"type": "approval", "question": "Q"}),
        ("other-type", "answer", {"type": "feature", "question": "Q"}),
        ("no-plan", "answer", {"type": "question", "question": "Q"}),
        ("no-question", "answer", {"type": "question"}),
    ]:
        plan = None if decision_id == "no-plan" else "plan"
        repo.project(projection(decision_id=decision_id, plan_id=plan, context=context))
        row = repo.submit_answer(decision_id, f"key-{decision_id}", "main", body).entry
        repo.transition_entry(row.entry_id, "delivered", "stored", "delivered")
        if decision_id in {
            "q",
            "approved",
            "approved-prefix",
            "rejected",
            "other-type",
            "no-plan",
            "no-question",
        }:
            repo.record_writeback_audit(
                decision_id, "plan-write-failed", row.entry_id, "failed"
            )
    candidates = repo.writeback_candidates()
    assert [row.decision_id for row in candidates] == [
        "q",
        "approved",
        "approved-prefix",
        "rejected",
        "other-type",
        "no-plan",
        "no-question",
    ]
    repo.project(projection(decision_id="never-failed"))
    unattempted = repo.submit_answer(
        "never-failed", "key-never-failed", "main", "body"
    ).entry
    repo.transition_entry(unattempted.entry_id, "delivered", "stored", "delivered")
    assert "never-failed" not in {
        row.decision_id for row in repo.writeback_candidates()
    }
    q = next(row for row in candidates if row.decision_id == "q")
    repo.record_writeback_audit("q", "plan-written", q.entry_id, "done")
    approved = next(row for row in candidates if row.decision_id == "approved")
    repo.record_writeback_audit(
        "approved", "plan-write-failed", approved.entry_id, "failed"
    )
    assert {row.decision_id for row in repo.writeback_candidates()} == {
        "approved",
        "approved-prefix",
        "rejected",
        "other-type",
        "no-plan",
        "no-question",
    }
    repo.record_writeback_audit(
        "approved", "plan-write-failed", approved.entry_id, "failed"
    )
    assert {row.decision_id for row in repo.writeback_candidates()} == {
        "approved-prefix",
        "rejected",
        "other-type",
        "no-plan",
        "no-question",
    }
    with pytest.raises(NotFound):
        repo.record_writeback_audit("missing", "plan-write-failed", "x", "failed")


def test_concurrent_submit_is_exclusive(repo: DecisionRepository) -> None:
    repo.project(projection())
    barrier = Barrier(12)

    def submit(i: int):
        barrier.wait()
        try:
            return repo.submit_answer("d1", f"key-{i}", "main", str(i))
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(submit, range(12)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert sum(row.reason == "answer stored" for row in repo.audit_rows("d1")) == 1
    decision = repo.get_decision("d1")
    assert decision is not None and decision.state == "answered"


def test_concurrent_same_key_replays_one_answer(repo: DecisionRepository) -> None:
    repo.project(projection())
    barrier = Barrier(12)

    def submit(_: int):
        barrier.wait()
        return repo.submit_answer("d1", "same-key", "main", "same body")

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(submit, range(12)))
    assert len({result.entry.entry_id for result in results}) == 1
    assert sum(result.replayed for result in results) == 11
    assert sum(row.reason == "answer stored" for row in repo.audit_rows()) == 1


def test_reads_never_write_and_return_detached_state(repo: DecisionRepository) -> None:
    repo.project(projection())
    row = repo.submit_answer("d1", "key", "main", "answer").entry

    def full_state():
        return (
            repo.version(),
            repo.list_decisions(),
            repo.audit_rows(),
            tuple(
                (status, repo.entries_by_status(status))
                for status in ("stored", "sending", "delivered", "failed")
            ),
            repo.writeback_candidates(),
        )

    before_state = full_state()
    decision = repo.get_decision("d1")
    assert decision is not None
    decision.source_msg_ids.append("corruption")
    decision.record["context"]["question"] = "corruption"
    entry = repo.get_entry("key")
    assert entry == row
    assert repo.permission_entry("key") is False
    assert repo.latest_delivered_reply("d1") is None
    assert repo.writeback_candidates() == []
    audit = repo.audit_rows()[0]
    audit.msg_ids.append("corruption")
    assert full_state() == before_state
    with pytest.raises(Invalid):
        repo.dismiss("")


def test_note_path_and_byte_writes(repo: DecisionRepository) -> None:
    repo.project(DecisionProjection("s", "permission", "permission", "t", "b", {}))
    entry = repo.submit_answer("permission", "key", "main", "body").entry
    assert repo.notes_path(entry.entry_id) == entry.notes_path
    path = repo.write_answer_note(entry.entry_id, "naïve\n".encode())
    assert Path(path).read_bytes() == "naïve\n".encode()
    with pytest.raises(NotFound):
        repo.write_answer_note("missing", b"data")
