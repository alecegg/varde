from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

from varde_data.records.messages import Message, NewMessage
from varde_runner.decisions import DecisionProjection, DecisionStore
from varde_runner.open_decisions import open_decision_items
from varde_runner.varde_cli import VardeCLI


def test_decision_store_close_waits_for_database_users(tmp_path, monkeypatch):
    store = DecisionStore(tmp_path, send=lambda **_kwargs: {})
    repository = store.repository
    version_read = threading.Event()
    allow_close = threading.Event()
    reader_started = threading.Event()
    reader_done = threading.Event()
    reader_results = []
    closer = None
    version = repository.version

    def pause_close_version():
        result = version()
        if threading.current_thread() is closer:
            version_read.set()
            assert allow_close.wait(2)
        return result

    def read_version():
        reader_started.set()
        try:
            reader_results.append(repository.version())
        except sqlite3.ProgrammingError as error:
            reader_results.append(error)
        finally:
            reader_done.set()

    monkeypatch.setattr(repository, "version", pause_close_version)
    closer = threading.Thread(target=store.close)
    reader = threading.Thread(target=read_version)
    closer.start()
    assert version_read.wait(2)
    reader.start()
    assert reader_started.wait(2)
    try:
        assert not reader_done.wait(0.1)
    finally:
        allow_close.set()
    closer.join(2)
    reader.join(2)

    assert not closer.is_alive()
    assert not reader.is_alive()
    assert len(reader_results) == 1
    assert isinstance(reader_results[0], sqlite3.ProgrammingError)


def present[T](value: T | None) -> T:
    assert value is not None
    return value


def app_request(app, method: str, path: str, payload: dict[str, Any] | None = None):
    body = json.dumps(payload or {}).encode()
    messages = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"host", b"localhost:8765"),
                    (b"content-type", b"application/json"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8765),
            },
            receive,
            send,
        )
    )
    start = messages[0]
    content = b"".join(message.get("body", b"") for message in messages[1:])
    headers = dict(start.get("headers", []))
    return start["status"], headers, content


def create_decision_app(tmp_path, working: Path, messages, monkeypatch):
    from varde_runner.web import create_app

    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "messages.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "ts": "2026-10-20T12:00:00Z",
                    "from": message["from"],
                    "to": "main",
                    "kind": message["kind"],
                    "text": message.get("text", "Decision request"),
                    "id": message["id"],
                    "notes": message["notes"],
                }
            )
            + "\n"
            for message in messages
        ),
        encoding="utf-8",
    )
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})
    monkeypatch.setattr(cli, "send", lambda **kwargs: {"id": "sent-answer"})
    monkeypatch.setattr(cli, "read_plan", dict)
    return create_app(data_dir=tmp_path / "runner", cli=cli, bound_port=8765)


def load_decision_fixture(name: str) -> dict[str, Any]:
    fixture_dir = Path(__file__).parent / "fixtures" / "decisions"
    data = json.loads((fixture_dir / name).read_text(encoding="utf-8"))
    evidence = data.get("evidence", [])
    if isinstance(evidence, list):
        for entry in evidence:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                entry["path"] = str((fixture_dir / entry["path"]).resolve())
    return data


def test_decision_fixtures_resolve_evidence_paths_at_test_time():
    fixture_dir = Path(__file__).parent / "fixtures" / "decisions"
    for name in (
        "info.json",
        "merge-approval.json",
        "question.json",
        "unsandboxed-approval.json",
    ):
        fixture = load_decision_fixture(name)
        for entry in fixture["evidence"]:
            if "path" in entry:
                path = Path(entry["path"])
                assert path.is_absolute()
                assert path.is_relative_to(fixture_dir.resolve())


def test_answer_stores_full_text_then_sends_one_summary(tmp_path):
    text = ("🙂漢字e\u0301 אבג\r\n" * 2000)[:20_000]
    assert len(text) == 20_000
    calls = []

    def send(*, sender, recipient, kind, text, notes):
        calls.append((sender, recipient, kind, text, notes))
        return {"id": "m-delivery"}

    store = DecisionStore(tmp_path, send=send)
    result = store.submit_answer("d-1", "key-1", "agent-1", text)
    assert result.status == "delivered"
    assert present(store.get_entry("key-1")).body.encode() == text.encode()
    assert result.notes_path is not None
    assert Path(result.notes_path).read_bytes() == text.encode()
    assert len(calls) == 1
    assert calls[0][3] and "\n" not in calls[0][3] and "\r" not in calls[0][3]
    assert len(calls[0][3].encode()) <= 1000
    store.close()


def test_answer_limit_and_failed_retry_keep_text(tmp_path):
    def fail(**kwargs):
        raise RuntimeError("send failed")

    store = DecisionStore(tmp_path, send=fail)
    too_long = store.submit_answer("d", "too-long", "agent", "x" * 20_001)
    assert too_long.status_code == 413
    assert store.get_entry("too-long") is None
    failed = store.submit_answer("d", "retry-key", "agent", "body")
    assert failed.status == "failed"
    assert present(store.get_entry("retry-key")).body == "body"
    store.close()


def test_permission_answer_is_recorded_for_plugin_delivery(tmp_path):
    calls = []
    store = DecisionStore(
        tmp_path,
        send=lambda **kwargs: calls.append(kwargs) or {"id": "permission-message"},
    )
    store.project(
        DecisionProjection(
            source_id="permission-source",
            decision_id="permission",
            kind="permission",
            title="Permission",
            body="Allow command",
            context={},
        )
    )
    result = store.submit_answer("permission", "permission-key", "agent", "allow once")
    assert result.status == "stored"
    assert calls == []
    assert present(store.get_entry("permission-key")).body == "allow once"
    assert len(store.audit_rows()) == 1
    store.close()


def test_projector_preserves_approval_and_evidence_notes(tmp_path):
    from varde_runner.intake import InboxProjector

    attachment = tmp_path / "review.png"
    attachment.write_bytes(b"image")
    notes = tmp_path / "decision.json"
    notes.write_text(
        json.dumps(
            {
                "type": "approval",
                "approval": "merge",
                "title": "Merge dashboard work",
                "asked": "May I merge this plan?",
                "why": "The plan is ready for review.",
                "plan_id": "dashboard-decisions",
                "options": [],
                "recommendation": "approve",
                "evidence": [
                    {
                        "kind": "shot",
                        "caption": "Rendered mailbox",
                        "path": str(attachment),
                        "url": "https://example.test/track",
                    }
                ]
                + ["invalid", {"kind": "diff", "text": "stat", "url": "/api/admin"}],
            }
        ),
        encoding="utf-8",
    )
    store = DecisionStore(tmp_path / "decisions", send=lambda **kwargs: {})
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=lambda: [
            {
                "id": "approval-1",
                "from": "builder",
                "kind": "needs-user",
                "notes": str(notes),
                "text": "Merge dashboard work",
            }
        ],
        read_plan=dict,
        decision_store=store,
    )

    item = projector.project()[0]
    assert item.type == "approval"
    assert item.approval == "merge"
    assert item.title == "Merge dashboard work"
    assert item.evidence == [
        {"kind": "shot", "caption": "Rendered mailbox", "path": str(attachment)},
        {"kind": "diff", "text": "stat"},
    ]
    assert [option["id"] for option in item.options] == ["approve", "hold", "ask-more"]
    decision = store.get_decision("approval-1")
    assert decision is not None
    assert decision["context"]["evidence"] == item.evidence
    projector.close()
    store.close()


def test_projection_concurrent_writers_upsert_one_row(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from varde_runner.intake import InboxProjector

    message = {
        "id": "concurrent-question",
        "from": "builder",
        "kind": "needs-user",
        "text": "Choose an option",
    }
    context_barrier = Barrier(2)
    store = DecisionStore(tmp_path / "decisions", send=lambda **kwargs: {})
    projectors = [
        InboxProjector(
            tmp_path / "inbox.sqlite3",
            read_messages=lambda: [message],
            read_plan=dict,
            decision_store=store,
        )
        for _ in range(2)
    ]

    def read_context(notes: object) -> dict[str, Any]:
        context_barrier.wait(timeout=5)
        return {
            "type": "question",
            "asked": "Choose an option",
            "why": "A choice is needed",
            "options": [{"id": "yes", "label": "Yes"}],
        }

    for projector in projectors:
        projector._read_context = read_context

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda projector: projector.project(), projectors))

    assert all(len(result) == 1 for result in results)
    assert projectors[0].row_count() == 1
    for projector in projectors:
        projector.close()
    store.close()


def test_plain_question_keeps_legacy_decision_kind(tmp_path):
    from varde_runner.intake import InboxProjector

    notes = tmp_path / "question.json"
    notes.write_text(
        json.dumps(
            {
                "type": "question",
                "asked": "Which option?",
                "why": "A choice is needed.",
                "options": [{"id": "one", "label": "One"}],
            }
        ),
        encoding="utf-8",
    )
    store = DecisionStore(tmp_path / "decisions", send=lambda **kwargs: {})
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=lambda: [
            {
                "id": "question",
                "from": "builder",
                "kind": "needs-user",
                "notes": str(notes),
            }
        ],
        read_plan=dict,
        decision_store=store,
    )
    projector.project()
    decision = store.get_decision("question")
    assert decision is not None and decision["kind"] == "agent_question"
    projector.close()
    store.close()


def test_mailbox_evidence_route_enforces_plan_root_and_headers(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plans = working / "plans"
    plans.mkdir(parents=True)
    valid = plans / "review.txt"
    valid.write_text("evidence", encoding="utf-8")
    missing = plans / "missing.txt"
    outside = working / "private.txt"
    outside.write_text("private", encoding="utf-8")
    note = tmp_path / "decision.json"
    note.write_text(
        json.dumps(
            {
                "type": "question",
                "asked": "Review these files?",
                "why": "Check the evidence route.",
                "options": [{"id": "yes", "label": "Yes"}],
                "evidence": [
                    {"kind": "note", "path": str(valid)},
                    {"kind": "note", "path": str(outside)},
                    {"kind": "note", "path": str(missing)},
                ],
            }
        ),
        encoding="utf-8",
    )
    messages = [
        {
            "id": "evidence-decision",
            "from": "builder",
            "kind": "needs-user",
            "notes": str(note),
            "text": "Review these files?",
        }
    ]
    app = create_decision_app(tmp_path, working, messages, monkeypatch)
    assert app.state.dashboard.evidence_roots == (plans.resolve(),)
    from varde_runner.evidence import resolve_evidence_path

    assert (
        resolve_evidence_path(str(valid), app.state.dashboard.evidence_roots)
        == valid.resolve()
    )
    assert (
        asyncio.run(app.state.dashboard.mailbox_items())[0]["msg_id"]
        == "evidence-decision"
    )

    status, headers, body = app_request(
        app, "GET", "/api/mailbox/evidence-decision/evidence/0"
    )
    assert status == 200
    assert body == b"evidence"
    assert headers[b"content-type"] == b"text/plain; charset=utf-8"
    assert headers[b"x-content-type-options"] == b"nosniff"
    for index in (-1, 3, 1, 2):
        status, _, _ = app_request(
            app, "GET", f"/api/mailbox/evidence-decision/evidence/{index}"
        )
        assert status == 404


def test_mailbox_evidence_route_normalizes_non_list_evidence(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plans = working / "plans"
    plans.mkdir(parents=True)
    note = tmp_path / "bad-evidence.json"
    note.write_text(
        json.dumps(
            {
                "asked": "Review?",
                "why": "Evidence may be malformed.",
                "options": [{"id": "yes", "label": "Yes"}],
                "evidence": {"path": str(plans / "anything.txt")},
            }
        ),
        encoding="utf-8",
    )
    messages = [
        {
            "id": "bad-evidence",
            "from": "builder",
            "kind": "needs-user",
            "notes": str(note),
        }
    ]
    app = create_decision_app(tmp_path, working, messages, monkeypatch)
    assert app_request(app, "GET", "/api/mailbox/bad-evidence/evidence/0")[0] == 404
    assert app.state.dashboard.projector.project()[0].evidence == []


def test_approval_answers_validate_replay_conflict_and_keep_text(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plans = working / "plans"
    plans.mkdir(parents=True)
    messages = []
    decision_ids = (
        "approval",
        "permission",
        "approve-text",
        "approve-plain",
        "hold-text",
        "hold-plain",
    )
    for decision_id in decision_ids:
        note = tmp_path / f"{decision_id}.json"
        note.write_text(
            json.dumps(
                {
                    "type": "approval",
                    "asked": "May I proceed?",
                    "why": "This needs a decision.",
                    "options": [{"id": "custom", "label": "Custom"}],
                }
            ),
            encoding="utf-8",
        )
        messages.append(
            {
                "id": decision_id,
                "from": "builder",
                "kind": "permission" if decision_id == "permission" else "needs-user",
                "notes": str(note),
            }
        )
    app = create_decision_app(tmp_path, working, messages, monkeypatch)

    def answer(decision_id, key, option, text=""):
        return app_request(
            app,
            "POST",
            f"/api/mailbox/{decision_id}/answer",
            {"option": option, "text": text, "idempotency_key": key},
        )

    invalid_status, _, _ = answer("approval", "empty", "ask-more", "  \n")
    assert invalid_status == 400
    status, _, _ = answer("approval", "answer-1", "ask-more", "Need the test result")
    assert status == 200
    decisions = app.state.dashboard.decisions
    first = decisions.get_entry("answer-1")
    assert first is not None and first.body == "ASK-MORE: Need the test result"
    assert answer("approval", "answer-1", "ask-more", "Need the test result")[0] == 200
    assert answer("approval", "answer-2", "ask-more", "Need the test result")[0] == 409

    for decision_id, key, option, text, expected in (
        (
            "approve-text",
            "approve-key",
            "approve",
            "squash after merge",
            "APPROVED: squash after merge",
        ),
        ("approve-plain", "approve-plain-key", "approve", "", "APPROVED"),
        ("hold-text", "hold-key", "hold", "wait for CI", "HOLD: wait for CI"),
        ("hold-plain", "hold-plain-key", "hold", "", "HOLD"),
    ):
        status, _, _ = answer(decision_id, key, option, text)
        assert status == 200
        entry = decisions.get_entry(key)
        assert entry is not None and entry.body == expected

    permission_status, _, _ = answer("permission", "permission-key", "approve", "")
    assert permission_status == 200
    permission_entry = decisions.get_entry("permission-key")
    assert permission_entry is not None and permission_entry.body == "approve"


def test_answer_delivery_removes_message_from_open_inbox(tmp_path):
    from varde_runner.intake import InboxProjector
    from varde_runner.web.app import DashboardData, _mailbox_payload

    messages = [{"id": "question", "from": "agent@example.test", "kind": "needs-user"}]
    sent = []

    def send(**kwargs):
        message = {"id": "answer", **kwargs}
        sent.append(message)
        messages.append(message)
        return {"id": "answer"}

    store = DecisionStore(
        tmp_path / "answers", send=send, read_messages=lambda: messages
    )
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=lambda: messages,
        read_plan=dict,
        decision_store=store,
    )
    assert [item.msg_id for item in projector.project()] == ["question"]
    result = store.submit_answer("question", "key", "agent@example.test", "Done")
    assert result.status == "delivered"
    assert sent[0]["sender"] == "dashboard"
    assert sent[0]["recipient"] == "agent@example.test"
    assert sent[0]["kind"] == "info"
    projector.project()
    dashboard = DashboardData(None, projector, store, None)
    assert _mailbox_payload(dashboard.inbox())["open"] == []
    assert any(row["new_state"] == "delivered" for row in store.audit_rows())
    projector.close()
    store.close()


def test_failed_permission_delivery_can_be_retried(tmp_path):
    store = DecisionStore(tmp_path, send=lambda **_kwargs: {"id": "unused"})
    store.db.execute(
        "INSERT INTO decisions(decision_id,state,source_msg_ids,kind) "
        "VALUES ('permission', 'pending', '[\"request\"]', 'permission')"
    )
    store.db.commit()

    entry = store.submit_answer("permission", "permission-key", "builder", "allow")
    assert entry.status == "stored"
    assert entry.entry_id is not None
    entry_id = entry.entry_id
    decision = store.get_decision("permission")
    assert decision is not None
    assert decision["state"] == "answered"

    failed = store.resolve_permission(entry_id, success=False)
    assert failed.status == "failed"
    decision = store.get_decision("permission")
    assert decision is not None
    assert decision["state"] == "pending"
    assert decision["answer_key"] is None

    delivered = store.resolve_permission(entry_id, success=True)
    assert delivered.status == "delivered"
    decision = store.get_decision("permission")
    assert decision is not None
    assert decision["state"] == "answered"
    assert decision["answer_key"] == "permission-key"


def test_real_cli_decision_answer_returns_info_to_sender(tmp_path):
    """A plain info reply keeps answers deliverable by the LLM mailman path."""
    from varde_runner.web import create_app

    real_varde = shutil.which("varde")
    assert real_varde
    working, config, home = tmp_path / "working", tmp_path / "config", tmp_path / "home"
    for path in (working, config, home):
        path.mkdir()
    note = tmp_path / "question.json"
    note.write_text(
        json.dumps(
            {
                "type": "question",
                "title": "Choose a dashboard default",
                "asked": "Which default should the dashboard use?",
                "why": "The UI needs one stable starting point.",
                "options": [{"id": "compact", "label": "Compact"}],
                "recommendation": "compact",
            }
        ),
        encoding="utf-8",
    )
    cli = VardeCLI(
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_WORKING_DIR": str(working),
            "PATH": f"{os.path.dirname(real_varde)}:{os.environ['PATH']}",
        },
    )
    cli.send(
        sender="builder",
        recipient="main",
        kind="needs-user",
        text="Choose a dashboard default",
        notes=str(note),
    )
    app = create_app(data_dir=tmp_path / "runner", cli=cli, bound_port=8765)
    try:
        messages = []
        payload = json.dumps(
            {"option": "compact", "idempotency_key": "decision-answer"}
        ).encode()

        async def receive() -> dict:
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message: Any) -> None:
            messages.append(message)

        message_id = cli.read_messages()[0]["id"]
        path = f"/api/mailbox/{message_id}/answer"
        asyncio.run(
            app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "root_path": "",
                    "headers": [
                        (b"host", b"localhost:8765"),
                        (b"content-type", b"application/json"),
                    ],
                    "client": ("127.0.0.1", 1234),
                    "server": ("127.0.0.1", 8765),
                },
                receive,
                send,
            )
        )
        assert messages[0]["status"] == 200
        messages = cli.read_messages()
        replies = [
            message for message in messages if message.get("from") == "dashboard"
        ]
        assert len(replies) == 1
        assert replies[0]["to"] == "builder"
        assert replies[0]["kind"] == "info"
        assert replies[0]["text"] == f"re needs-user {message_id}: compact"
    finally:
        app.state.projector.close()
        app.state.decisions.close()


def test_terminal_decision_rejects_different_idempotency_key(tmp_path):
    calls = []
    store = DecisionStore(
        tmp_path, send=lambda **kwargs: calls.append(kwargs) or {"id": "m"}
    )
    first = store.submit_answer("d", "key-1", "agent", "one")
    second = store.submit_answer("d", "key-2", "agent", "two")
    assert first.status == "delivered"
    assert second.status_code == 409
    assert second.entry_id is None
    assert len(calls) == 1
    rows = store.audit_rows()
    assert (
        sum(
            row["prior_state"] == "pending" and row["new_state"] == "answered"
            for row in rows
        )
        == 1
    )
    store.close()


def test_decision_recorder_tracks_non_permission_projection_and_delivery(tmp_path):
    recorded = []
    store = DecisionStore(
        tmp_path,
        send=lambda **kwargs: {"id": "reply"},
        recorder=lambda event, decision: recorded.append((event, decision.copy())),
    )
    projection = DecisionProjection(
        source_id="source",
        decision_id="decision",
        kind="approval",
        title="Approve deployment",
        body="",
        context={"type": "approval"},
    )
    store.project(projection)
    store.project(projection)
    assert [event for event, _ in recorded] == ["created", "created"]
    result = store.submit_answer("decision", "answer-key", "agent", "APPROVED")
    assert result.status == "delivered"
    assert [event for event, _ in recorded] == ["created", "created", "answered"]
    assert recorded[-1][1]["answer"] == "APPROVED"
    store.close()


def test_decision_recorder_skips_permission_cards_and_contains_failures(tmp_path):
    def broken(_event, _decision):
        raise RuntimeError("metrics unavailable")

    store = DecisionStore(tmp_path, send=lambda **kwargs: {}, recorder=broken)
    store.project(
        DecisionProjection(
            source_id="permission",
            decision_id="permission",
            kind="permission",
            title="Permission",
            body="",
            context={},
        )
    )
    store.project(
        DecisionProjection(
            source_id="ordinary",
            decision_id="ordinary",
            kind="agent_question",
            title="Question",
            body="",
            context={},
        )
    )
    assert store.get_decision("ordinary") is not None
    result = store.submit_answer("ordinary", "answer-key", "agent", "reply")
    assert result.status == "delivered"
    store.close()


def test_open_mailbox_items_excludes_replied_acked_unbound_and_concluded(tmp_path):
    store = DecisionStore(tmp_path / "decisions", send=lambda **kwargs: {})
    messages = [
        {
            "id": "open",
            "from": "active-open",
            "kind": "needs-user",
            "ts": "2026-10-20T10:00:00Z",
        },
        {
            "id": "replied",
            "from": "active",
            "kind": "needs-user",
            "ts": "2026-10-20T11:00:00Z",
        },
        {
            "id": "acked",
            "from": "active",
            "kind": "needs-user",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "unbound",
            "from": "unbound",
            "kind": "needs-user",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "concluded",
            "from": "concluded",
            "kind": "needs-user",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "resolved",
            "from": "active",
            "kind": "needs-user",
            "ts": "2026-10-20T12:00:00Z",
        },
        {
            "id": "reply",
            "from": "main",
            "to": "active",
            "kind": "info",
            "ts": "2026-10-20T11:30:00Z",
        },
    ]
    items = [
        {
            "msg_id": message["id"],
            "sender": message["from"],
            "kind": message["kind"],
            "ts": message["ts"],
            "state": "dismissed" if message["id"] == "resolved" else "pending",
        }
        for message in messages
        if message["from"] != "main"
    ]

    result = open_decision_items(
        items,
        messages,
        {"acked"},
        {"active", "active-open", "concluded"},
        {"concluded"},
    )

    assert [item["msg_id"] for item in result] == ["open"]
    store.close()


def test_cli_failure_keeps_text_and_retry_delivers_once(tmp_path, monkeypatch):
    working, config, home = tmp_path / "working", tmp_path / "config", tmp_path / "home"
    for path in (working, config, home):
        path.mkdir()
    cli = VardeCLI(
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_WORKING_DIR": str(working),
        },
    )
    original_append = cli._messages.append
    attempts = 0

    def fail_first_append(message: NewMessage) -> Message:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("message store unavailable")
        return original_append(message)

    monkeypatch.setattr(cli._messages, "append", fail_first_append)
    store = DecisionStore(
        tmp_path / "store", send=cli.send, read_messages=cli.read_messages
    )
    failed = store.submit_answer("d", "same-key", "main", "body kept")
    assert failed.status == "failed"
    assert present(store.get_entry("same-key")).body == "body kept"
    monkeypatch.setattr(cli._messages, "append", original_append)
    delivered = store.retry("same-key")
    assert delivered.status == "delivered"
    messages = cli.read_messages()
    found = [item for item in messages if item.get("notes") == delivered.notes_path]
    assert len(found) == 1
    assert Path(present(found[0].get("notes"))).read_text() == "body kept"
    store.close()


def test_retry_recreates_notes_and_audits_delivery(tmp_path):
    attempts = 0

    def send(*, notes, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        assert Path(notes).read_bytes() == b"full answer"
        return {"id": "m-retried"}

    store = DecisionStore(tmp_path, send=send)
    failed = store.submit_answer("d", "key", "agent", "full answer")
    Path(present(failed.notes_path)).unlink()
    retried = store.retry("key")
    assert retried.status == "delivered"
    assert Path(present(retried.notes_path)).read_bytes() == b"full answer"
    rows = store.audit_rows()
    assert any(
        row["prior_state"] == "failed" and row["new_state"] == "sending" for row in rows
    )
    assert rows[-1]["prior_state"] == "sending"
    assert rows[-1]["new_state"] == "delivered"
    jsonl = [json.loads(line) for line in store.audit_path.read_text().splitlines()]
    assert [row["seq"] for row in jsonl] == [row["seq"] for row in rows]
    store.close()


def test_reused_idempotency_key_rejects_different_answer(tmp_path):
    store = DecisionStore(tmp_path, send=lambda **kwargs: {"id": "m"})
    first = store.submit_answer("d1", "same-key", "agent", "first")
    conflicting = store.submit_answer("d2", "same-key", "agent", "different")
    assert first.status == "delivered"
    assert conflicting.status_code == 409
    assert present(store.get_entry("same-key")).body == "first"
    store.close()


def test_real_cli_send_success_survives_failed_followup_read(tmp_path):
    real_varde = shutil.which("varde")
    assert real_varde
    working, config, home = tmp_path / "working", tmp_path / "config", tmp_path / "home"
    for path in (working, config, home):
        path.mkdir()
    wrapper_dir = tmp_path / "wrapper"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "varde"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "msg read" ]; then exit 17; fi\n'
        f'exec {real_varde} "$@"\n'
    )
    wrapper.chmod(0o755)
    cli = VardeCLI(
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_WORKING_DIR": str(working),
            "PATH": f"{wrapper_dir}:{os.environ['PATH']}",
        },
    )
    store = DecisionStore(tmp_path / "store", send=cli.send)
    result = store.submit_answer("d", "success-key", "main", "delivered")
    assert result.status == "delivered"
    real_cli = VardeCLI(
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_WORKING_DIR": str(working),
            "PATH": f"{os.path.dirname(real_varde)}:{os.environ['PATH']}",
        },
    )
    messages = real_cli.read_messages()
    assert len([msg for msg in messages if msg.get("notes") == result.notes_path]) == 1
    assert present(store.get_entry("success-key")).status == "delivered"
    store.close()


def test_restart_recovers_sending_from_real_cli_without_resending(tmp_path):
    real_varde = shutil.which("varde")
    assert real_varde
    working, config, home = tmp_path / "working", tmp_path / "config", tmp_path / "home"
    for path in (working, config, home):
        path.mkdir()
    cli = VardeCLI(
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_WORKING_DIR": str(working),
            "PATH": f"{os.path.dirname(real_varde)}:{os.environ['PATH']}",
        },
    )

    class SimulatedCrash(BaseException):
        pass

    def send_then_crash(**kwargs):
        cli.send(**kwargs)
        raise SimulatedCrash

    data_dir = tmp_path / "store"
    store = DecisionStore(
        data_dir, send=send_then_crash, read_messages=cli.read_messages
    )
    try:
        store.submit_answer("d", "crash-key", "main", "delivered once")
    except SimulatedCrash:
        pass
    else:
        raise AssertionError("send callback should simulate a process crash")
    assert present(store.get_entry("crash-key")).status == "sending"
    store.close()

    restarted = DecisionStore(data_dir, send=cli.send, read_messages=cli.read_messages)
    recovered = restarted.recover_sending()
    assert recovered[0].status == "delivered"
    messages = cli.read_messages()
    assert (
        len([msg for msg in messages if msg.get("notes") == recovered[0].notes_path])
        == 1
    )
    restarted.close()


def test_concurrent_duplicate_key_sends_once(tmp_path):
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        return {"id": "m-one"}

    store = DecisionStore(tmp_path, send=send)

    async def submit():
        return await asyncio.gather(
            *[
                asyncio.to_thread(store.submit_answer, "d", "same", "agent", "answer")
                for _ in range(2)
            ]
        )

    results = asyncio.run(submit())
    assert len({result.entry_id for result in results}) == 1
    assert len(calls) == 1
    rows = store.audit_rows()
    assert (
        sum(
            row["prior_state"] == "pending" and row["new_state"] == "answered"
            for row in rows
        )
        == 1
    )
    store.close()
