from __future__ import annotations

import contextlib
import datetime as datetime_module
import io
import itertools
import json
import os
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_workflow.inbox import append_message, record_relay_event
from varde_workflow.relay_state import mark_address_concluded

FIXED_NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
GOLDEN_DIR = Path(__file__).parent / "golden" / "msg"


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(FIXED_NOW.timestamp(), UTC)
        return value if tz is None else value.astimezone(tz)


def _prepare(working: Path, monkeypatch, *, git_root: Path | None = None) -> None:
    working.mkdir(parents=True)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    monkeypatch.setattr(datetime_module, "datetime", FixedDateTime)
    from varde_workflow import binding
    from varde_workflow import inbox as workflow_inbox

    ids = itertools.count(1)
    monkeypatch.setattr(workflow_inbox, "datetime", FixedDateTime)
    monkeypatch.setattr(secrets, "token_hex", lambda _size: f"{next(ids):08x}")

    issue = binding.BindingStore.issue
    redeem = binding.BindingStore.redeem

    def issue_with_fixture_source(self, *args, **kwargs):
        marker = issue(self, *args, **kwargs)
        next(ids)
        return marker

    def redeem_with_fixture_source(self, *args, **kwargs):
        result = redeem(self, *args, **kwargs)
        if result:
            for _ in range(3):
                next(ids)
        return result

    monkeypatch.setattr(binding.BindingStore, "issue", issue_with_fixture_source)
    monkeypatch.setattr(binding.BindingStore, "redeem", redeem_with_fixture_source)
    if git_root is not None:
        subprocess.run(["git", "init", "-q", str(git_root)], check=True)  # noqa: S603, S607


def _cli(argv: list[str], root: Path) -> dict[str, object]:
    from varde_workflow.cli import run

    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = run(argv)
    return {
        "exit": code,
        "stdout": stdout.getvalue().replace(str(root), "<TMP>"),
        "stderr": stderr.getvalue().replace(str(root), "<TMP>"),
    }


def _bytes(path: Path) -> str:
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def _store(working: Path, *relative_paths: str) -> dict[str, str]:
    return {relative: _bytes(working / relative) for relative in relative_paths}


def _snapshot(
    name: str,
    classification: str,
    root: Path,
    value: dict[str, object],
) -> None:
    assert classification in {"unchanged", "intentional-change"}
    rendered = (
        json.dumps(
            {"classification": classification, **value},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    rendered = rendered.replace(str(root), "<TMP>")
    path = GOLDEN_DIR / f"{name}.json"
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == rendered


def test_msg_send_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    from varde_workflow.slots import add_alias

    add_alias(working, "orchestrator-1", "plan-a")
    notes = working / "decision.json"
    notes.write_text('{"decision":"yes"}\n', encoding="utf-8")
    output = {
        "plain": _cli(
            ["send", "--from", "builder", "--to", "main", "--kind", "info", "plain"],
            tmp_path,
        ),
        "notes": _cli(
            [
                "send",
                "--from",
                "builder",
                "--to",
                "main",
                "--kind",
                "needs-user",
                "--notes",
                "decision.json",
                "review",
            ],
            tmp_path,
        ),
        "alias_target": _cli(
            ["send", "--from", "builder", "--to", "plan-a", "--kind", "done", "alias"],
            tmp_path,
        ),
        "validation": _cli(
            ["send", "--from", "bad address", "--to", "main", "--kind", "info", "bad"],
            tmp_path,
        ),
    }
    _snapshot(
        "send",
        "intentional-change",
        tmp_path,
        {
            "stdout_stderr": output,
            "store": _store(
                working,
                ".cache/inbox/messages.jsonl",
                ".cache/inbox/relay/state.json",
                ".cache/inbox/slots/orchestrator-1.json",
            ),
        },
    )


def test_msg_read_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    messages = [
        append_message("sender", "worker", "info", text, working=working, now=FIXED_NOW)
        for text in ("first", "second")
    ]
    output = {
        "all": _cli(["read", "--as", "worker", "--all", "--json"], tmp_path),
        "claim": _cli(["read", "--as", "worker", "--json"], tmp_path),
        "empty": _cli(["read", "--as", "worker", "--json"], tmp_path),
    }
    _snapshot(
        "read",
        "unchanged",
        tmp_path,
        {
            "stdout_stderr": output,
            "message_ids": [message.id for message in messages],
            "store": _store(
                working,
                ".cache/inbox/messages.jsonl",
                ".cache/inbox/deliveries.jsonl",
                ".cache/inbox/index/worker.json",
            ),
        },
    )


def test_msg_ack_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    first = append_message(
        "sender", "worker", "info", "delivered", working=working, now=FIXED_NOW
    )
    second = append_message(
        "sender", "worker", "info", "wrong reader", working=working, now=FIXED_NOW
    )
    _cli(["read", "--as", "worker", "--json"], tmp_path)
    output = {
        "ok": _cli(["msg", "ack", first.id or "", "--as", "worker"], tmp_path),
        "not_delivered": _cli(["msg", "ack", "m-ffffffff", "--as", "worker"], tmp_path),
        "wrong_reader": _cli(
            ["msg", "ack", second.id or "", "--as", "other"], tmp_path
        ),
    }
    _snapshot(
        "ack",
        "unchanged",
        tmp_path,
        {
            "stdout_stderr": output,
            "store": _store(
                working,
                ".cache/inbox/messages.jsonl",
                ".cache/inbox/deliveries.jsonl",
                ".cache/inbox/index/worker.json",
            ),
        },
    )


def test_msg_status_golden(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    working = repo / "memory-bank" / "working"
    repo.mkdir()
    _prepare(working, monkeypatch, git_root=repo)
    stray = repo / "runner" / "memory-bank" / "working" / ".cache" / "inbox"
    stray.mkdir(parents=True)
    (stray / "messages.jsonl").write_text(
        json.dumps({"id": "m-stray", "to": "main", "text": "recover"}) + "\n"
    )
    append_message(
        "sender", "worker", "info", "below watermark", working=working, now=FIXED_NOW
    )
    legacy = {
        "ts": "2026-10-22T11:40:00Z",
        "from": "sender",
        "to": "legacy",
        "kind": "info",
        "text": "legacy",
    }
    inbox = working / ".cache" / "inbox"
    with (inbox / "messages.jsonl").open("ab") as stream:
        stream.write(json.dumps(legacy, separators=(",", ":")).encode() + b"\n")
    index = inbox / "index" / "worker.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text('{"watermark":1}\n', encoding="utf-8")
    from varde_workflow.binding import BindingStore
    from varde_workflow.commands.msg_status import status_messages

    stale_at = FIXED_NOW - timedelta(hours=1)
    bindings = BindingStore(working)
    marker = bindings.issue("stale-reader", now=stale_at)
    assert bindings.redeem(
        marker, "stale-session", "claude", str(working), now=stale_at
    )
    append_message(
        "sender",
        "stale-reader",
        "info",
        "stopped reading",
        working=working,
        now=FIXED_NOW - timedelta(minutes=20),
    )
    output = {
        "json": _cli(["msg", "status", "--json", "--now", FIXED_NOW.isoformat()], repo),
        "text": _cli(["msg", "status", "--now", FIXED_NOW.isoformat()], repo),
    }
    _snapshot(
        "status",
        "intentional-change",
        tmp_path,
        {
            "stdout_stderr": output,
            "message_rows": status_messages(inbox),
            "store": _store(
                working,
                ".cache/inbox/messages.jsonl",
                ".cache/inbox/index/worker.json",
                ".cache/inbox/index/stale-reader.json",
            ),
        },
    )


def test_msg_relay_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    delivered = append_message(
        "sender", "reader-a", "info", "delivered", working=working, now=FIXED_NOW
    )
    pushed = append_message(
        "sender", "reader-b", "info", "pushed", working=working, now=FIXED_NOW
    )
    busy = append_message(
        "sender", "reader-c", "info", "busy", working=working, now=FIXED_NOW
    )
    first = {
        "delivered": record_relay_event(
            working,
            delivered.id or "",
            "reader-a",
            "delivered",
            now=FIXED_NOW,
            via="hook",
        ),
        "pushed": record_relay_event(
            working, pushed.id or "", "reader-b", "pushed", now=FIXED_NOW, via="relay"
        ),
        "skipped_busy": record_relay_event(
            working,
            busy.id or "",
            "reader-c",
            "skipped-busy",
            now=FIXED_NOW,
            via="relay",
        ),
    }
    repeat = {
        "delivered": record_relay_event(
            working,
            delivered.id or "",
            "reader-a",
            "delivered",
            now=FIXED_NOW,
            via="hook",
        ),
        "pushed": record_relay_event(
            working, pushed.id or "", "reader-b", "pushed", now=FIXED_NOW, via="relay"
        ),
        "skipped_busy": record_relay_event(
            working,
            busy.id or "",
            "reader-c",
            "skipped-busy",
            now=FIXED_NOW,
            via="relay",
        ),
    }
    _snapshot(
        "relay",
        "unchanged",
        tmp_path,
        {
            "first_call": first,
            "repeat_call": repeat,
            "store": _store(
                working,
                ".cache/inbox/messages.jsonl",
                ".cache/inbox/deliveries.jsonl",
                ".cache/inbox/index/reader-a.json",
            ),
        },
    )


def test_torn_tail_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    original = append_message(
        "sender", "main", "info", "valid prefix", working=working, now=FIXED_NOW
    )
    messages = working / ".cache" / "inbox" / "messages.jsonl"
    with messages.open("ab") as stream:
        stream.write(b'{"ts":"torn')
    after_torn = _cli(["msg", "read", "--as", "main", "--all", "--json"], tmp_path)
    append_message(
        "sender", "main", "info", "after torn", working=working, now=FIXED_NOW
    )
    after_append = _cli(
        ["msg", "status", "--json", "--now", FIXED_NOW.isoformat()], tmp_path
    )
    _snapshot(
        "torn_tail",
        "intentional-change",
        tmp_path,
        {
            "valid_id": original.id,
            "read_after_torn": after_torn,
            "status_after_append": after_append,
            "store": _store(working, ".cache/inbox/messages.jsonl"),
        },
    )


def test_alias_ack_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    from varde_workflow.slots import add_alias

    add_alias(working, "orchestrator-1", "old-plan")
    sent = _cli(
        [
            "send",
            "--from",
            "sender",
            "--to",
            "old-plan",
            "--kind",
            "info",
            "alias mail",
        ],
        tmp_path,
    )
    from varde_workflow.inbox import read_all

    message = read_all(working)[0]
    assert message.to == "orchestrator-1"
    from varde_workflow.inbox import record_delivery

    record_delivery(
        working,
        message.id or "",
        "old-plan",
        "delivered",
        via="relay",
        now=FIXED_NOW.isoformat(),
    )
    ack = _cli(["msg", "ack", message.id or "", "--as", "old-plan"], tmp_path)
    _snapshot(
        "alias_ack",
        "intentional-change",
        tmp_path,
        {
            "send": sent,
            "ack_alias": ack,
            "store": _store(
                working,
                ".cache/inbox/slots/orchestrator-1.json",
                ".cache/inbox/messages.jsonl",
                ".cache/inbox/deliveries.jsonl",
            ),
        },
    )


def test_concluded_address_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    _prepare(working, monkeypatch)
    mark_address_concluded(working, "finished-plan")
    _snapshot(
        "concluded",
        "intentional-change",
        tmp_path,
        {
            "current_location": _store(working, ".cache/inbox/relay/state.json"),
            "design_location": _store(working, ".cache/inbox/state.json"),
        },
    )


# Intentional changes recorded for the follow-up implementation tasks:
# - `torn_tail`: prefix torn bytes with `b"\n"`; expected boundary bytes become
#   `b'{"ts":"torn\n{"ts":"<fixed timestamp>"'` before the appended row.
# - `alias_ack`: resolve `old-plan` to `orchestrator-1`; expected delivered and
#   ack rows both include `b'"reader":"orchestrator-1"'`.
# - `concluded`: move concluded state to `.cache/inbox/state.json`; expected
#   bytes there are `b'{"concluded_addresses":["finished-plan"]}\n'`.
