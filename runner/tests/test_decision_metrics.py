import asyncio
from types import SimpleNamespace

from test_supervisor import FakePlugin
from varde_runner.decision_metrics import (
    candidates,
    card_kind_for,
    classify_request_kind,
    plan_from_branch,
    redact_request_key,
    response_for_answer,
    summarize,
)
from varde_runner.decisions import DecisionProjection, DecisionStore
from varde_runner.plugins import RunnerCapabilities
from varde_runner.store import SessionStore
from varde_runner.supervisor import Supervisor
from varde_runner.waits import approval_wait_id
from varde_runner.web.card_metrics import CardMetricsRecorder


def test_classifies_request_shapes():
    assert (
        classify_request_kind({"tool": "shell", "input": {"command": "git status"}})
        == "command_prefix"
    )
    assert (
        classify_request_kind({"tool": "read", "input": {"path": "/repo/src/a.py"}})
        == "path_scope"
    )
    assert classify_request_kind({"url": "https://example.test"}) == "network"
    assert classify_request_kind({"tool": "other"}) == "other"
    assert classify_request_kind({"env": {"FOO": "bar"}}) == "other"


def test_redacts_command_path_and_url_secrets(tmp_path):
    marker = "sk-live-abc123"
    command = {"command": f"API_KEY={marker} git status {marker}"}
    path = {"path": str(tmp_path / "src" / marker / ".env")}
    url = {"url": f"https://x.test/?token={marker}"}
    values = [
        redact_request_key("command_prefix", command),
        redact_request_key("path_scope", path, str(tmp_path)),
        redact_request_key("network", url),
    ]
    assert values == ["command_prefix:git", "path_scope:src/*", "network"]
    assert all(
        marker not in value and ".env" not in value and "?" not in value
        for value in values
    )


def test_path_key_requires_known_root_and_uses_only_safe_directories(tmp_path):
    path = {"path": str(tmp_path / "src" / "ghp_xxx" / ".env")}
    assert redact_request_key("path_scope", path) == "path_scope:*"
    assert (
        redact_request_key("path_scope", path, str(tmp_path / "other"))
        == "path_scope:*"
    )
    assert redact_request_key("path_scope", {"path": ".env"}, ".") == "path_scope:*"
    assert (
        redact_request_key(
            "path_scope",
            {"path": str(tmp_path / "src" / "lib" / "module.py")},
            str(tmp_path),
        )
        == "path_scope:src/lib"
    )


def test_plan_from_worktree_branch():
    assert plan_from_branch("worktree/feature-name") == "feature-name"
    assert plan_from_branch("main") is None


def test_card_kind_for_decision_shapes():
    assert card_kind_for({"kind": "merge_ready"}) == "merge"
    assert card_kind_for({"kind": "design_decision"}) == "design_decision"
    assert (
        card_kind_for(
            {"kind": "agent_question", "plan_id": "p1", "context": {"type": "question"}}
        )
        == "plan_question"
    )
    assert card_kind_for({"kind": "agent_question"}) == "other"


def test_response_for_answer_maps_supported_choices():
    approval = {"kind": "approval", "context": {"type": "approval"}}
    design = {"kind": "design_decision", "context": {"type": "design_decision"}}
    question = {"kind": "agent_question", "context": {"type": "question"}}
    other = {"kind": "agent_question", "context": {}}

    assert response_for_answer("APPROVED: Looks good", approval) == "approve"
    assert response_for_answer("HOLD: Needs work", approval) == "deny"
    assert response_for_answer("ASK-MORE: Clarify", approval) == "ask_more"
    assert response_for_answer("free form answer", design) == "approve"
    assert response_for_answer("option-id\nexplanation", question) == "approve"
    assert response_for_answer("free form answer", other) == "approve"


def test_summarize_counts_rates_median_and_week_bucket():
    rows = [
        {
            "created_at": "2026-10-19T10:00:00+00:00",
            "role": "builder",
            "response": "approve",
            "time_to_answer_s": 2,
            "request_key": "command_prefix:git",
        },
        {
            "created_at": "2026-10-20T10:00:00+00:00",
            "role": "builder",
            "response": "approve",
            "time_to_answer_s": 6,
            "request_key": "command_prefix:git",
        },
        {
            "created_at": "2026-10-21T10:00:00+00:00",
            "role": "builder",
            "response": "deny",
            "time_to_answer_s": 10,
            "request_key": "command_prefix:git",
        },
        {
            "created_at": "2026-10-22T10:00:00+00:00",
            "role": "builder",
            "response": "expired",
            "time_to_answer_s": None,
            "request_key": "command_prefix:git",
        },
    ]
    result = summarize(rows, "role")
    assert result == [
        {
            "group": "builder",
            "count": 4,
            "responses": {"approve": 2, "deny": 1, "ask_more": 0, "expired": 1},
            "approve_rate": 0.5,
            "deny_rate": 0.25,
            "expired_rate": 0.25,
            "median_time_to_answer_s": 6.0,
        }
    ]
    assert summarize(rows, "week")[0]["group"] == "2026-10-19"
    assert candidates(rows) == []


def test_candidates_excludes_denied_and_ask_more_requests():
    rows = [{"request_key": "a", "response": "approve"} for _ in range(3)]
    rows += [{"request_key": "b", "response": "approve"} for _ in range(3)]
    rows += [{"request_key": "b", "response": "ask_more"}]
    assert candidates(rows) == ["a"]


def test_card_metrics_recorder_flushes_before_new_events_and_discards_answer_text():
    async def run():
        events = []
        answered = asyncio.Event()

        class MetricStore:
            def record_decision_event(self, request_id, **values):
                events.append(("created", request_id, values))

            def answer_decision_event(self, request_id, response):
                events.append(("answered", request_id, response))
                answered.set()

        class SupervisorStub:
            store = MetricStore()

        async def get_supervisor():
            return SupervisorStub()

        recorder = CardMetricsRecorder(get_supervisor)
        decision = {
            "decision_id": "card-1",
            "kind": "design_decision",
            "context": {"type": "design_decision"},
        }
        recorder("created", decision)
        recorder.bind_loop()
        recorder("answered", {**decision, "answer": "private answer text"})
        await asyncio.wait_for(answered.wait(), timeout=1)
        assert [event[0] for event in events] == ["created", "answered"]
        assert events[-1] == ("answered", "card-1", "approve")

    asyncio.run(run())


def test_card_row_metrics_record_kind_and_answer_for_supported_cards(tmp_path):
    async def run():
        session_store = SessionStore(tmp_path / "session-store")

        async def get_supervisor():
            return SimpleNamespace(store=session_store)

        recorder = CardMetricsRecorder(get_supervisor)
        recorder.bind_loop()
        decisions = DecisionStore(
            tmp_path / "decisions",
            send=lambda **kwargs: {"id": "reply"},
            recorder=recorder,
        )
        projections = [
            DecisionProjection(
                source_id="source-merge",
                decision_id="merge-ready",
                kind="merge_ready",
                title="Merge ready",
                body="",
                context={"type": "approval"},
            ),
            DecisionProjection(
                source_id="source-design",
                decision_id="design-decision",
                kind="design_decision",
                title="Choose a design",
                body="",
                context={"type": "design_decision"},
            ),
            DecisionProjection(
                source_id="source-question",
                decision_id="plan-question",
                kind="agent_question",
                title="Choose a plan option",
                body="",
                context={"type": "question", "options": ["option-a"]},
                plan_id="plan-1",
            ),
        ]
        for projection in projections:
            decisions.project(projection)
            result = decisions.submit_answer(
                projection.decision_id,
                f"answer-{projection.decision_id}",
                "agent",
                "APPROVED" if projection.decision_id == "merge-ready" else "option-a",
            )
            assert result.status == "delivered"

        rows = session_store.decision_events()
        for _ in range(100):
            rows = session_store.decision_events()
            if len(rows) == 3 and all(row["response"] is not None for row in rows):
                break
            await asyncio.sleep(0.01)
        assert {
            row["request_id"]: (row["card_kind"], row["response"]) for row in rows
        } == {
            "merge-ready": ("merge", "approve"),
            "design-decision": ("design_decision", "approve"),
            "plan-question": ("plan_question", "approve"),
        }
        decisions.close()
        session_store.close()

    asyncio.run(run())


def test_store_decision_event_reads_and_approved_before(tmp_path):
    store = SessionStore(tmp_path)
    store.record_decision_event(
        "first", request_key="command_prefix:git", response="approve"
    )
    store.record_decision_event("first", request_key="ignored", response="deny")
    store.record_decision_event("second", request_key="command_prefix:git")
    assert store.approved_before("command_prefix:git")
    assert [row["request_id"] for row in store.decision_events()] == ["first", "second"]
    assert [row["request_id"] for row in store.decision_events("9999")] == []
    assert store.has_decision_event("first")
    assert not store.has_decision_event("missing")
    indexes = {
        row["name"]
        for row in store.connection.execute("PRAGMA index_list(decision_event)")
    }
    assert "decision_event_request_key_idx" in indexes


def test_permission_row_attributes_and_redacts_payload(tmp_path):
    async def run():
        plugin = FakePlugin(
            RunnerCapabilities(), str(tmp_path / "pid"), str(tmp_path / "prompt")
        )
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.upsert_workspace(
            "w1", repo_root="/repo", cwd=str(tmp_path), branch="worktree/example"
        )
        supervisor.store.create_session(
            "s1",
            "fake",
            {},
            "builder",
            harness="codex",
            model="model-x",
            mode="full-access",
            workspace_id="w1",
        )
        marker = "TOKEN_secret-shaped"
        await supervisor.record_event(
            "s1",
            "permission_requested",
            {
                "request_id": "r1",
                "command": f"git status {marker}",
                "path": str(tmp_path / "src" / marker / ".env"),
                "url": f"https://example.test/?token={marker}",
            },
        )
        row = supervisor.store.decision_events()[0]
        assert (row["role"], row["harness"], row["model"], row["harness_mode"]) == (
            "builder",
            "codex",
            "model-x",
            "full-access",
        )
        assert row["plan"] == "example"
        assert row["card_kind"] == "permission"
        assert row["request_kind"] == "command_prefix"
        assert row["request_key"] == "command_prefix:git"
        assert row["response"] is None
        assert marker not in repr(row)
        await supervisor.shutdown()

    asyncio.run(run())


def test_repeat_permission_key_tracks_prior_approval(tmp_path):
    async def run():
        plugin = FakePlugin(
            RunnerCapabilities(respond=True),
            str(tmp_path / "pid"),
            str(tmp_path / "prompt"),
        )
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session("s1", "fake", {}, "builder")
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1", "command": "git status"}
        )
        from varde_runner.plugins import SessionRef

        supervisor._refs["s1"] = SessionRef("fake", "remote")
        assert await supervisor.respond("s1", "r1", "approve") == "responded"
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r2", "command": "git diff"}
        )
        assert supervisor.store.decision_events()[-1]["approved_before"] == 1
        await supervisor.shutdown()

    asyncio.run(run())


def test_permission_recording_is_idempotent_and_approved_before_starts_false(tmp_path):
    async def run():
        plugin = FakePlugin(
            RunnerCapabilities(), str(tmp_path / "pid"), str(tmp_path / "prompt")
        )
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session("s1", "fake", {}, "builder")
        payload = {"request_id": "r1", "command": "git status"}
        await supervisor.record_event("s1", "permission_requested", payload)
        await supervisor.record_event("s1", "permission_requested", payload)
        row = supervisor.store.decision_events()[0]
        assert row["request_key"] == "command_prefix:git"
        assert row["approved_before"] == 0
        assert len(supervisor.store.decision_events()) == 1
        await supervisor.shutdown()

    asyncio.run(run())


def test_backfill_closes_resolved_request_in_event_order(tmp_path):
    async def run():
        plugin = FakePlugin(
            RunnerCapabilities(), str(tmp_path / "pid"), str(tmp_path / "prompt")
        )
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session("s1", "fake", {}, "builder")
        supervisor.store.append_event(
            "s1", "permission_requested", {"request_id": "r1", "command": "git status"}
        )
        supervisor.store.append_event(
            "s1", "permission_resolved", {"request_id": "r1", "decision": "allow"}
        )
        supervisor._backfill_approval_waits()
        row = supervisor.store.decision_events()[0]
        assert row["request_id"] == approval_wait_id("s1", "r1")
        assert row["response"] == "approve"
        assert row["answered_at"] is not None
        assert supervisor.store.get_wait("approval:s1:r1") is None
        await supervisor.shutdown()

    asyncio.run(run())


def test_missing_workspace_never_stores_absolute_path(tmp_path):
    async def run():
        plugin = FakePlugin(
            RunnerCapabilities(), str(tmp_path / "pid"), str(tmp_path / "prompt")
        )
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session("s1", "fake", {}, "builder")
        await supervisor.record_event(
            "s1",
            "permission_requested",
            {"request_id": "r1", "path": str(tmp_path / "private" / ".env")},
        )
        row = supervisor.store.decision_events()[0]
        assert row["request_key"] == "path_scope:*"
        assert str(tmp_path) not in repr(row)
        await supervisor.shutdown()

    asyncio.run(run())


def test_identical_request_ids_are_scoped_by_session(tmp_path):
    async def run():
        plugin = FakePlugin(
            RunnerCapabilities(), str(tmp_path / "pid"), str(tmp_path / "prompt")
        )
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session("s1", "fake", {}, "builder")
        supervisor.store.create_session("s2", "fake", {}, "builder")
        for session_id in ("s1", "s2"):
            await supervisor.record_event(
                session_id,
                "permission_requested",
                {"request_id": "same", "command": "git status"},
            )
        assert {row["request_id"] for row in supervisor.store.decision_events()} == {
            approval_wait_id("s1", "same"),
            approval_wait_id("s2", "same"),
        }
        await supervisor.shutdown()

    asyncio.run(run())
