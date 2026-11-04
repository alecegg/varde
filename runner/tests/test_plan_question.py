from __future__ import annotations

import asyncio
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from varde_runner.decisions import DecisionProjection, DecisionStore
from varde_runner.varde_cli import VardeCLI


def _store(tmp_path: Path, **options: Any) -> DecisionStore:
    decision_type = options.get("decision_type", "question")
    plan_id = options.get("plan_id", "sample-plan")
    question = options.get("question", "Which route?")
    store = DecisionStore(
        tmp_path / "decisions",
        send=options.get("send") or (lambda **_kwargs: {"id": "answer-message"}),
        read_messages=options.get("read_messages"),
        write_back=options.get("write_back"),
    )
    store.project(
        DecisionProjection(
            source_id="request-message",
            decision_id="request-message",
            kind="agent_question",
            title="Question",
            body="Question body",
            context={"type": decision_type, "question": question},
            plan_id=plan_id,
            source_agent="planner",
        )
    )
    return store


def test_plan_question_writeback_uses_context_and_audits_success(
    tmp_path: Path,
) -> None:
    calls = []
    store = _store(
        tmp_path,
        write_back=lambda plan_id, question, answer: calls.append(
            (plan_id, question, answer)
        ),
    )

    result = store.submit_answer("request-message", "key", "planner", "Use route A")
    assert result.status == "delivered"
    assert calls == [("sample-plan", "Which route?", "Use route A")]
    assert any(row["new_state"] == "plan-written" for row in store.audit_rows())
    store.recover_sending()
    assert len(calls) == 1
    store.close()


def test_plan_question_intake_carries_question_from_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_runner.intake import InboxProjector

    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    notes = tmp_path / "question.json"
    notes.write_text(
        '{"type":"question","asked":"Which route?","why":"Choose one",'
        '"options":[{"id":"a","label":"A"}],"plan_id":"sample-plan",'
        '"question":"Which route?"}',
        encoding="utf-8",
    )
    store = DecisionStore(tmp_path / "decisions", send=lambda **_kwargs: {})
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=lambda: [
            {
                "id": "question-message",
                "from": "planner",
                "kind": "needs-user",
                "notes": str(notes),
                "text": "Question",
            }
        ],
        read_plan=lambda: {"events": []},
        decision_store=store,
    )

    projector.project()

    decision = store.get_decision("question-message")
    assert decision is not None
    assert decision["context"]["question"] == "Which route?"
    assert decision["context"]["source_kind"] == "needs-user"
    projector.close()
    store.close()


@pytest.mark.parametrize(
    ("decision_type", "body"),
    [("approval", "HOLD"), ("approval", "ASK-MORE: details")],
)
def test_plan_question_writeback_skips_nonresolving_answers(
    tmp_path: Path, decision_type: str, body: str
) -> None:
    calls = []
    store = _store(
        tmp_path,
        write_back=lambda *args: calls.append(args),
        decision_type=decision_type,
    )
    assert (
        store.submit_answer("request-message", "key", "planner", body).status
        == "delivered"
    )
    assert calls == []
    store.close()


@pytest.mark.parametrize(("plan_id", "question"), [(None, "Question?"), ("plan", None)])
def test_plan_question_writeback_skips_missing_tags(
    tmp_path: Path, plan_id: str | None, question: str | None
) -> None:
    calls = []
    store = _store(
        tmp_path,
        write_back=lambda *args: calls.append(args),
        plan_id=plan_id,
        question=question,
    )
    assert (
        store.submit_answer("request-message", "key", "planner", "Answer").status
        == "delivered"
    )
    assert calls == []
    store.close()


def test_plan_question_writeback_failure_retries_after_delivery(tmp_path: Path) -> None:
    calls = []

    def write_back(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("plan is temporarily unavailable")

    store = _store(tmp_path, write_back=write_back)
    result = store.submit_answer("request-message", "key", "planner", "Use A")
    assert result.status == "delivered"
    assert [row["new_state"] for row in store.audit_rows()][-1] == "plan-write-failed"

    store.retry_plan_writebacks()
    assert calls == [
        ("sample-plan", "Which route?", "Use A"),
        ("sample-plan", "Which route?", "Use A"),
    ]
    entry = store.get_entry("key")
    assert entry is not None
    assert entry.status == "delivered"
    assert [row["new_state"] for row in store.audit_rows()][-1] == "plan-written"
    store.recover_sending()
    assert len(calls) == 2
    store.close()


def test_mailbox_projection_retries_failed_plan_writeback(tmp_path: Path) -> None:
    from varde_runner.intake import InboxProjector

    calls = []

    def write_back(*args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("plan is temporarily unavailable")

    store = _store(tmp_path, write_back=write_back)
    assert (
        store.submit_answer("request-message", "key", "planner", "Use A").status
        == "delivered"
    )
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=list,
        read_plan=lambda: {"events": []},
        decision_store=store,
    )

    projector.project()

    assert calls == [
        ("sample-plan", "Which route?", "Use A"),
        ("sample-plan", "Which route?", "Use A"),
    ]
    assert store.audit_rows()[-1]["new_state"] == "plan-written"
    projector.close()
    store.close()


def test_plan_question_writeback_runs_after_reconciled_delivery(tmp_path: Path) -> None:
    messages = []
    calls = []

    def send(**kwargs):
        messages.append({"notes": kwargs["notes"], "id": "reconciled-message"})
        raise RuntimeError("delivery response was lost")

    store = _store(
        tmp_path,
        send=send,
        read_messages=lambda: messages,
        write_back=lambda *args: calls.append(args),
    )
    assert (
        store.submit_answer("request-message", "key", "planner", "Use B").status
        == "failed"
    )
    assert store.retry("key").status == "delivered"
    assert calls == [("sample-plan", "Which route?", "Use B")]
    assert sum(row["new_state"] == "plan-written" for row in store.audit_rows()) == 1
    store.close()


def test_plan_question_writeback_calls_real_cli_with_bare_plan_id(
    tmp_path: Path,
) -> None:
    worktree = Path(__file__).resolve().parents[2]
    working = tmp_path / "working"
    plan = working / "plans" / "bare-plan-id" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: bare-plan-id\n---\n## Open Questions\n- Which route?\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    varde = bin_dir / "varde"
    varde.write_text(
        f"#!/bin/sh\nexec uv run --project '{worktree}' varde \"$@\"\n",
        encoding="utf-8",
    )
    varde.chmod(varde.stat().st_mode | stat.S_IXUSR)
    cli = VardeCLI(
        cwd=worktree,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "VARDE_WORKING_DIR": str(working),
        },
    )

    cli.answer_plan_question("bare-plan-id", "Which route?", "Use route A")
    assert cli.answer_plan_question("bare-plan-id", "Which route?", "Use route A") == {
        "plan": str(plan.resolve()),
        "question": "Which route?",
        "updated": False,
    }

    updated = plan.read_text(encoding="utf-8")
    assert "Which route? → Use route A (" in updated
    assert "## Open Questions\n\nn/a — no open questions" in updated


def test_plan_question_cli_uses_json_argv_and_timeout(monkeypatch, tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, '{"data":{"updated":true}}', "")

    monkeypatch.setattr("varde_runner.varde_cli.subprocess.run", run)
    result = VardeCLI(cwd=tmp_path).answer_plan_question("plan", "Q?", "A")

    assert result == {"updated": True}
    assert calls[0][0] == [
        "varde",
        "plan",
        "answer",
        "plan",
        "--question",
        "Q?",
        "--answer",
        "A",
        "--json",
    ]
    assert calls[0][1]["timeout"] == 30


def test_plan_question_writeback_retries_are_capped(tmp_path: Path) -> None:
    calls = []

    def fail(*args):
        calls.append(args)
        raise RuntimeError("question is no longer open")

    store = _store(tmp_path, write_back=fail)
    result = store.submit_answer("request-message", "key", "planner", "Use A")
    assert result.status == "delivered"
    for _ in range(5):
        store.recover_sending()

    assert len(calls) == 3
    failures = [
        row for row in store.audit_rows() if row["new_state"] == "plan-write-failed"
    ]
    assert len(failures) == 3
    entry = store.get_entry("key")
    assert entry is not None and entry.status == "delivered"
    store.close()


def test_plan_question_recovery_selects_only_failed_writebacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    should_fail = True

    def write_back(_plan_id: str, question: str, _answer: str) -> None:
        nonlocal should_fail
        if question == "Needs retry?" and should_fail:
            should_fail = False
            raise RuntimeError("temporary failure")

    store = _store(tmp_path, write_back=write_back, question="Already done?")
    done = store.submit_answer("request-message", "done", "planner", "Yes")
    store.project(
        DecisionProjection(
            source_id="retry-message",
            decision_id="retry-message",
            kind="agent_question",
            title="Question",
            body="Question body",
            context={"type": "question", "question": "Needs retry?"},
            plan_id="sample-plan",
            source_agent="planner",
        )
    )
    failed = store.submit_answer("retry-message", "retry", "planner", "Later")
    assert done.entry_id is not None and failed.entry_id is not None
    attempts = []
    monkeypatch.setattr(store, "_write_back_entry", attempts.append)

    store.recover_sending()

    assert attempts == [failed.entry_id]
    store.close()


def test_dashboard_startup_runs_decision_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_runner.web import create_app

    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    store = DecisionStore(tmp_path / "decisions", send=lambda **_kwargs: {})
    recovered = []
    monkeypatch.setattr(store, "recover_sending", lambda: recovered.append(True) or [])
    cli = type(
        "FakeCLI",
        (),
        {
            "env": {"VARDE_WORKING_DIR": str(tmp_path)},
            "cwd": tmp_path,
            "send": lambda *_args, **_kwargs: {},
            "read_messages": lambda *_args: [],
            "read_plan": lambda *_args: {"events": []},
        },
    )()
    app = create_app(data_dir=tmp_path / "runner", cli=cli, decisions=store)

    async def start_and_stop() -> None:
        async with app.router.lifespan_context(app):
            assert recovered == [True]

    asyncio.run(start_and_stop())
    store.close()
