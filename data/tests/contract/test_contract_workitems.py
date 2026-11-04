from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from varde_data.errors import Invalid, NotFound
from varde_data.repos.workitems import WorkItemRepository
from workitems_backends import Backend, backend_registry


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def backend(request: pytest.FixtureRequest) -> Backend:
    return backend_registry()[request.param]


@pytest.fixture
def items(backend: Backend, tmp_path: Path) -> WorkItemRepository:
    return backend.factory(tmp_path)


def test_create_validation_and_idempotency(items: WorkItemRepository) -> None:
    created = items.create("key", "request", "project")
    assert items.create("key", "ignored", "elsewhere") == created
    assert items.by_key("key") == created
    assert items.get(created.id) == created
    assert len(items.list()) == 1
    for args in (("", "ok", "project"), ("k", "ok", ""), ("k", "x" * 20_001, "p")):
        with pytest.raises(Invalid):
            items.create(*args)
    with pytest.raises(NotFound):
        items.get("missing")


def test_transitions_questions_answers_and_audit(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    assert items.claim_planner_start(item.id)
    assert not items.claim_planner_start(item.id)
    assert items.reset_planner_start(item.id).state == "new"
    assert items.start_planning(item.id, "session").planner_session == "session"
    assert items.for_planner_session("session") == items.get(item.id)
    payload = {"asked": "Choose?"}
    assert items.record_question(item.id, "q1", payload)
    assert not items.record_question(item.id, "q1", payload)
    assert items.questions(item.id)[0].payload == payload
    assert items.answer(item.id, "q1", "A", "answer-key")
    assert not items.answer(item.id, "q1", "A", "answer-key")
    assert items.attach_planner(item.id, "session-2").planner_session == "session-2"
    assert items.plan_ready(item.id, "plan.md", "ready-1").state == "ready"
    assert items.plan_ready(item.id, "other.md", "ready-2").plan_ready_id == "ready-1"
    assert items.decide(item.id, True).state == "queued"
    assert items.decide(item.id, False).state == "queued"
    rows = items.audit(item.id)
    assert [row.new_state for row in rows] == [
        "new",
        "planning",
        "new",
        "planning",
        "asking",
        "planning",
        "ready",
        "queued",
    ]
    assert [(row.prior_state, row.new_state, row.detail) for row in rows] == [
        (None, "new", "submitted"),
        ("new", "planning", "planner start claimed"),
        ("planning", "new", "planner start recovered for retry"),
        ("new", "planning", "planner started"),
        ("planning", "asking", "question q1"),
        ("asking", "planning", "question q1 answered"),
        ("planning", "ready", "plan ready"),
        ("ready", "queued", "user decision"),
    ]
    assert [row.detail for row in rows][0:5] == [
        "submitted",
        "planner start claimed",
        "planner start recovered for retry",
        "planner started",
        "question q1",
    ]


def test_terminal_stability_fail_and_launch_request(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "session")
    items.plan_ready(item.id, "plan", "ready")
    assert items.claim_launch_request(item.id, "request.json")
    assert not items.claim_launch_request(item.id, "other.json")
    saved = items.record_launch_request(item.id, "launch-1", "request.json")
    assert saved.launch_request_id == "launch-1"
    items.release_launch_request(item.id)
    assert items.get(item.id).launch_request_id == "launch-1"
    assert items.fail(item.id, "failure").state == "queued"


def test_rejected_terminal_stability_and_failure(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "session")
    items.plan_ready(item.id, "plan", "ready")
    assert items.decide(item.id, False).state == "rejected"
    assert items.fail(item.id, "failure").state == "rejected"


def test_concurrent_planner_claim_is_exclusive(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    barrier = Barrier(12)

    def claim(_: int) -> bool:
        barrier.wait()
        return items.claim_planner_start(item.id)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(claim, range(12)))
    assert sum(results) == 1


def test_concurrent_launch_request_claim_is_exclusive(
    items: WorkItemRepository,
) -> None:
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "session")
    items.plan_ready(item.id, "plan", "ready")
    barrier = Barrier(12)

    def claim(_: int) -> bool:
        barrier.wait()
        return items.claim_launch_request(item.id, "notes")

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(claim, range(12)))
    assert sum(results) == 1


def test_contract_edges_and_question_order(items: WorkItemRepository) -> None:
    assert not items.claim_planner_start("missing")
    items.release_launch_request("missing")
    item = items.create("key", "request", "project")
    other = items.create("key-2", "request 2", "project")
    assert [row.id for row in items.list()] == [item.id, other.id]
    assert items.attach_planner(item.id, "ignored").planner_session is None
    with pytest.raises(Invalid):
        items.record_question(other.id, "bad", {})
    items.start_planning(item.id, "session")
    with pytest.raises(Invalid):
        items.decide(item.id, True)
    items.record_question(item.id, "b", {"asked": "B"})
    items.record_question(item.id, "a", {"asked": "A"})
    assert [question.msg_id for question in items.questions(item.id)] == ["a", "b"]
    copied = items.questions(item.id)
    copied[0].payload["asked"] = "mutated"
    assert items.questions(item.id)[0].payload["asked"] == "A"
    assert items.answer(item.id, "a", "answer A", "key-a")
    assert items.get(item.id).state == "asking"
    with pytest.raises(NotFound):
        items.answer(item.id, "unknown", "x", "x")
    assert items.answer(item.id, "b", "answer B", "key-b")
    assert items.get(item.id).state == "planning"


def test_answer_reverts_any_state_when_all_questions_answered(
    items: WorkItemRepository,
) -> None:
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "session")
    items.record_question(item.id, "q1", {})
    items.plan_ready(item.id, "plan", "ready")
    assert items.answer(item.id, "q1", "answer", "key")
    assert items.get(item.id).state == "planning"
    assert items.audit(item.id)[-1].prior_state == "asking"


def test_invalid_states_and_version_noops(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    version = items.version()
    assert items.start_planning(item.id, "first").state == "planning"
    version = items.version()
    assert items.start_planning(item.id, "ignored").planner_session == "first"
    assert items.version() == version
    with pytest.raises(Invalid):
        items.decide(item.id, False)
    fresh = items.create("fresh", "request", "project")
    with pytest.raises(Invalid):
        items.decide(fresh.id, False)
    items.fail(item.id, "failure")
    assert items.get(item.id).state == "failed"
    with pytest.raises(Invalid):
        items.plan_ready(item.id, "plan", "ready")
    assert items.decide(item.id, True).state == "failed"
    assert items.fail(item.id, "again").state == "failed"
    assert items.version() != version


def test_multiple_question_answers_keep_asking_until_last(
    items: WorkItemRepository,
) -> None:
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "session")
    items.record_question(item.id, "q2", {"asked": "Second"})
    items.record_question(item.id, "q1", {"asked": "First"})
    assert items.answer(item.id, "q1", "first answer", "key-1")
    assert items.get(item.id).state == "asking"
    assert items.answer(item.id, "q2", "second answer", "key-2")
    assert items.get(item.id).state == "planning"


def test_note_path_validation_and_missing_owner(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    for name in ("", ".", "../outside"):
        with pytest.raises(Invalid):
            items.write_note(item.id, name, "bad")
    sibling = items.write_note(item.id, "context.txt", "owned")
    another = items.create("other", "other", "project")
    assert items.owns_note(another.id, sibling) is False
    assert items.owns_note("missing", sibling) is False
    # Request-note replacement is permitted, matching write_note's file semantics.
    request_note = items.write_note(item.id, "request.md", "replacement")
    assert Path(request_note).read_text(encoding="utf-8") == "replacement"


def test_reads_do_not_write(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    before = items.version()
    items.get(item.id)
    items.by_key("key")
    items.list()
    items.for_planner_session("none")
    items.questions(item.id)
    items.audit(item.id)
    assert items.version() == before


def test_every_write_transition_bumps_version(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")

    def assert_bumped(operation) -> None:
        before = items.version()
        operation()
        assert items.version() != before

    assert_bumped(lambda: items.claim_planner_start(item.id))
    assert_bumped(lambda: items.reset_planner_start(item.id))
    assert_bumped(lambda: items.start_planning(item.id, "session"))
    assert_bumped(lambda: items.attach_planner(item.id, "session-2"))
    assert_bumped(lambda: items.record_question(item.id, "q1", {"asked": "A"}))
    assert_bumped(lambda: items.answer(item.id, "q1", "A", "answer-key"))
    assert_bumped(lambda: items.plan_ready(item.id, "plan", "ready"))
    assert_bumped(lambda: items.decide(item.id, True))
    assert_bumped(lambda: items.claim_launch_request(item.id, "notes"))
    assert_bumped(lambda: items.record_launch_request(item.id, "launch", "notes"))
    assert_bumped(lambda: items.write_note(item.id, "context.md", "context"))
    before = items.version()
    items.release_launch_request(item.id)
    assert items.version() == before


def test_notes_ownership_and_version(items: WorkItemRepository) -> None:
    item = items.create("key", "request", "project")
    before = items.version()
    note = items.write_note(item.id, "context/data.json", "{}")
    assert Path(note).is_absolute()
    assert items.owns_note(item.id, note)
    assert not items.owns_note(item.id, str(Path(note).parents[2] / "outside"))
    assert items.version() != before
