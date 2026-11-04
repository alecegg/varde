from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from varde_runner.decisions import DecisionStore
from varde_runner.intake import InboxProjector
from varde_runner.varde_cli import VardeCLI


def test_projects_complete_and_missing_context_once(tmp_path):
    complete = tmp_path / "complete.json"
    complete.write_text(
        json.dumps(
            {
                "asked": "choose",
                "why": "blocks",
                "options": [{"label": "yes", "consequence": "go"}],
            }
        )
    )
    messages = [
        {
            "id": "m1",
            "from": "a",
            "to": "main",
            "kind": "needs-user",
            "text": "choose",
            "notes": str(complete),
        },
        {
            "id": "m2",
            "from": "b",
            "to": "main",
            "kind": "needs-user",
            "text": "question",
            "notes": str(tmp_path / "missing.json"),
        },
        {
            "id": "m3",
            "from": "c",
            "to": "main",
            "kind": "needs-user",
            "text": "bare",
            "notes": None,
        },
    ]
    projector = InboxProjector(
        tmp_path / "db.sqlite3",
        read_messages=lambda: messages,
        read_plan=lambda: {"plans": []},
    )
    first = projector.project()
    assert len(first) == 3
    assert first[0].needs_context is False
    assert first[1].needs_context is True
    assert first[2].needs_context is True
    assert len(projector.project()) == 3
    assert projector.row_count() == 3
    projector.close()


def test_projector_refreshes_context_and_creates_plan_decisions(tmp_path):
    late_notes = tmp_path / "late.json"
    messages = [
        {
            "id": "m-late",
            "from": "agent",
            "to": "main",
            "kind": "needs-user",
            "text": "question",
            "notes": str(late_notes),
        }
    ]
    plan_state = {
        "events": [{"kind": "blocked", "plan": "plan-a", "text": "needs decision"}]
    }
    decisions = DecisionStore(tmp_path / "decisions", send=lambda **kwargs: {"id": "m"})
    projector = InboxProjector(
        tmp_path / "projection.sqlite3",
        read_messages=lambda: messages,
        read_plan=lambda: plan_state,
        decision_store=decisions,
    )
    first = projector.project()
    assert first[0].needs_context is True
    decision = decisions.get_decision("plan-a:blocked")
    assert decision is not None
    assert decision["plan_id"] == "plan-a"
    late_notes.write_text(
        json.dumps(
            {
                "asked": "question",
                "why": "blocks work",
                "options": [{"label": "continue", "consequence": "unblocks"}],
                "recommendation": "continue",
                "sources": ["plan-a"],
            }
        )
    )
    second = projector.project()
    assert len(second) == 1
    assert second[0].needs_context is False
    assert second[0].asked == "question"
    assert projector.row_count() == 1
    projector.close()
    decisions.close()


def test_real_cli_notes_round_trip_in_isolated_state(tmp_path):
    working = tmp_path / "working"
    config = tmp_path / "config"
    home = tmp_path / "home"
    working.mkdir()
    config.mkdir()
    home.mkdir()
    cli = VardeCLI(
        cwd=tmp_path,
        env={
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_WORKING_DIR": str(working),
        },
    )
    text = ("🙂漢字e\u0301 אבג\r\n" * 2000)[:20_000]
    assert len(text) == 20_000
    long_store_path = working / ("n" * 180) / ".cache" / "dashboard"
    store = DecisionStore(long_store_path, send=cli.send)
    result = store.submit_answer("d-real", "real-key", "main", text)
    assert result.status == "delivered"
    emoji = store.submit_answer("d-emoji", "emoji-key", "main", "🙂" * 200)
    cjk = store.submit_answer("d-cjk", "cjk-key", "main", "漢" * 400)
    assert emoji.status == cjk.status == "delivered"
    messages = cli.read_messages()
    message = next(item for item in messages if item.get("notes") == result.notes_path)
    assert message["text"]
    assert Path(message["notes"]).read_bytes() == text.encode()
    raw_read = subprocess.run(
        ["varde", "msg", "read", "--all", "--json"],  # noqa: S607 - Test resolves the installed Varde CLI from PATH.
        cwd=tmp_path,
        env=cli.env,
        capture_output=True,
        check=True,
    ).stdout
    assert result.notes_path is not None
    assert result.notes_path.encode() in raw_read
    assert text.encode() not in raw_read
    for delivered in (emoji, cjk):
        summary_message = next(
            item for item in messages if item.get("notes") == delivered.notes_path
        )
        assert (
            len(summary_message["text"].encode())
            + len(summary_message["notes"].encode())
            <= 1000
        )
    store.close()


def test_plan_watch_cli_is_read_without_inbox_or_wake_side_effects(tmp_path):
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
    assert cli.read_plan() == {"events": []}
    assert not (working / "inbox").exists()


def test_concurrent_duplicate_answers_send_one_real_cli_message(tmp_path):
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
    store = DecisionStore(working / ".cache" / "dashboard", send=cli.send)
    results = asyncio.run(_concurrent_submit(store))
    assert len({result.entry_id for result in results}) == 1
    assert results[0].status == "delivered"
    messages = cli.read_messages()
    assert (
        len([msg for msg in messages if msg.get("notes") == results[0].notes_path]) == 1
    )
    store.close()


def test_answer_for_running_recipient_uses_cli_without_plugin_send(tmp_path):
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

    class RunningPlugin:
        state = "running"
        send_calls = 0

        async def send(self, ref, prompt):
            self.send_calls += 1

    plugin = RunningPlugin()
    store = DecisionStore(
        working / ".cache" / "dashboard", send=cli.send, read_messages=cli.read_messages
    )
    result = store.submit_answer("d-running", "running-key", "active-agent", "reply")
    assert result.status == "delivered"
    assert plugin.state == "running"
    assert plugin.send_calls == 0
    assert (
        len(
            [
                msg
                for msg in cli.read_messages()
                if msg.get("notes") == result.notes_path
            ]
        )
        == 1
    )
    store.close()


async def _concurrent_submit(store):
    return await asyncio.gather(
        *[
            asyncio.to_thread(
                store.submit_answer,
                "d-real-concurrent",
                "same-real-key",
                "main",
                "one answer",
            )
            for _ in range(2)
        ]
    )
