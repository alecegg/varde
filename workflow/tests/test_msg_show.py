from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime

from varde_workflow.inbox import append_message, record_relay_event


def test_msg_show_text_and_json_report_state_and_reply(tmp_path, monkeypatch) -> None:
    from varde_workflow.cli import _parser

    parsed = _parser().parse_args(
        [
            "msg",
            "send",
            "--from",
            "reader",
            "--to",
            "sender",
            "--kind",
            "info",
            "--reply-to",
            "m-12345678",
            "answer",
        ]
    )
    assert parsed.reply_to == "m-12345678"
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    original = append_message(
        "sender",
        "reader",
        "info",
        "question",
        working=working,
        now=datetime(2026, 10, 24, 10, tzinfo=UTC),
    )
    assert original.id is not None
    record_relay_event(
        working,
        original.id,
        "reader",
        "pushed",
        now=datetime(2026, 10, 24, 10, 1, tzinfo=UTC),
        action_created_at="2026-10-24T10:01:00Z",
        reason="steer",
    )
    record_relay_event(
        working,
        original.id,
        "reader",
        "failed",
        now=datetime(2026, 10, 24, 10, 1, 30, tzinfo=UTC),
        action_created_at="2026-10-24T10:01:30Z",
        reason="provider timeout",
    )
    record_relay_event(
        working,
        original.id,
        "reader",
        "delivered",
        now=datetime(2026, 10, 24, 10, 2, tzinfo=UTC),
        via="receipt",
    )
    append_message(
        "reader",
        "sender",
        "info",
        "answer",
        working=working,
        now=datetime(2026, 10, 24, 10, 3, tzinfo=UTC),
        reply_to=original.id,
    )
    from varde_workflow.cli import run

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert run(["show", original.id]) == 0
    assert "[answered] question" in stdout.getvalue()
    assert "read: 2026-10-24T10:02:00Z" in stdout.getvalue()
    assert "last reason: provider timeout" in stdout.getvalue()
    assert "delivered-as: steer" in stdout.getvalue()

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert run(["show", original.id, "--json"]) == 0
    report = json.loads(stdout.getvalue())
    assert report["state"] == "answered"
    assert "reply_to" not in report
    assert report["last_reason"] == "provider timeout"
    assert report["delivered_as"] == "steer"
    assert report["timestamps"]["answered"] == "2026-10-24T10:03:00Z"
