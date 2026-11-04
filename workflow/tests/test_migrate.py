from __future__ import annotations

import json
import re
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_workflow.commands.msg import delivery_events, read_all, unread
from varde_workflow.commands.msg_migrate import run_migration
from varde_workflow.commands.msg_status import run as run_status
from varde_workflow.inbox import Message


def test_migration_replays_urgent_caps_and_marks_history_once(tmp_path: Path) -> None:
    now = datetime(2026, 10, 17, tzinfo=UTC)
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    messages = [
        Message(
            (now - timedelta(hours=1)).isoformat(),
            "worker",
            "old",
            "blocked",
            f"urgent {n}",
            id=f"m-{n:08d}",
        )
        for n in range(32)
    ]
    messages += [
        Message(
            (now - timedelta(hours=1)).isoformat(),
            "worker",
            "finished",
            "info",
            "closed plan",
            id="m-finished",
        ),
        Message(
            (now - timedelta(days=3)).isoformat(),
            "worker",
            "old",
            "info",
            "old history",
            id="m-old",
        ),
    ]
    (inbox / "messages.jsonl").write_text(
        "".join(item.to_json() + "\n" for item in messages)
    )
    (inbox / "index").mkdir()
    (inbox / "index" / "main.json").write_text(
        json.dumps({"watermark": (inbox / "messages.jsonl").stat().st_size})
    )

    assert run_migration(tmp_path, now=now, plans={"finished": "completed"}) == 0
    replayed = [
        json.loads(line)
        for line in (inbox / "messages.jsonl").read_text().splitlines()[len(messages) :]
    ]
    assert len(replayed) == 30
    assert replayed[0]["text"] == "urgent 31"
    assert all(item["to"] == "main" and item["legacy"] is True for item in replayed)
    events = delivery_events(tmp_path)
    assert any(
        item["message_id"] == "m-finished" and item["event"] == "dropped"
        for item in events
    )
    assert any(
        item["message_id"] == "m-old" and item["event"] == "legacy" for item in events
    )
    assert len(unread(tmp_path, "main")) == 30
    snapshot = (
        (inbox / "messages.jsonl").read_bytes(),
        (inbox / "deliveries.jsonl").read_bytes(),
    )
    assert run_migration(tmp_path, now=now, plans={"finished": "completed"}) == 0
    assert snapshot == (
        (inbox / "messages.jsonl").read_bytes(),
        (inbox / "deliveries.jsonl").read_bytes(),
    )


def test_stray_migration_dry_run_apply_dedupes_and_removes_only_empty_dirs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory
    from varde_workflow.commands.msg_migrate import migrate_strays

    repo = tmp_path / "repo"
    repo.mkdir()
    working = repo / "memory-bank" / "working"
    real_inbox = working / ".cache" / "inbox"
    real_inbox.mkdir(parents=True)
    existing = {"id": "m-existing", "to": "main", "text": "kept"}
    (real_inbox / "messages.jsonl").write_text(json.dumps(existing) + "\n")
    stray_inbox = repo / "nested" / "memory-bank" / "working" / ".cache" / "inbox"
    stray_inbox.mkdir(parents=True)
    unseen = {"id": "m-unseen", "to": "main", "text": "copied"}
    (stray_inbox / "messages.jsonl").write_text(
        "\n".join(json.dumps(item) for item in (existing, unseen, unseen)) + "\n"
    )
    (stray_inbox.parent.parent.parent / "keep.txt").write_text("keep")
    monkeypatch.setattr(memory, "find_root", lambda *_args, **_kwargs: repo)

    before = (real_inbox / "messages.jsonl").read_bytes()
    assert migrate_strays(working) == 0
    assert (real_inbox / "messages.jsonl").read_bytes() == before
    assert stray_inbox.is_dir()
    assert "Would merge 1 message from 1 stray store." in capsys.readouterr().out

    assert migrate_strays(working, apply=True) == 0
    capsys.readouterr()
    merged = [
        json.loads(line)
        for line in (real_inbox / "messages.jsonl").read_text().splitlines()
    ]
    assert [item["id"] for item in merged] == ["m-existing", "m-unseen"]
    assert not stray_inbox.exists()
    assert stray_inbox.parents[2].is_dir()
    assert (stray_inbox.parent.parent.parent / "keep.txt").read_text() == "keep"
    assert migrate_strays(working, apply=True) == 0
    merged_again = (real_inbox / "messages.jsonl").read_bytes()
    assert len(merged_again.splitlines()) == 2


def test_stray_migration_keeps_malformed_and_idless_messages(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory
    from varde_workflow.commands.msg_migrate import migrate_strays

    repo = tmp_path / "repo"
    repo.mkdir()
    working = repo / "memory-bank" / "working"
    stray = repo / "nested" / "memory-bank" / "working" / ".cache" / "inbox"
    stray.mkdir(parents=True)
    inbox_file = stray / "messages.jsonl"
    inbox_file.write_text('{"id":"m-ok"}\nnot json\n{"text":"idless"}\n')
    monkeypatch.setattr(memory, "find_root", lambda *_args, **_kwargs: repo)

    assert migrate_strays(working, apply=True) == 0
    output = capsys.readouterr().out
    assert "Skipped 2 malformed or id-less lines" in output
    assert f"Kept stray store: {stray}" in output
    assert inbox_file.exists()


def test_migration_status_matches_ids_for_idless_legacy_lines(
    tmp_path: Path, capsys
) -> None:
    now = datetime.now(UTC)
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "messages.jsonl").write_text(
        json.dumps(
            {
                "ts": now.isoformat(),
                "from": "worker",
                "to": "finished",
                "kind": "info",
                "text": "legacy update",
            }
        )
        + "\n"
    )

    assert run_migration(tmp_path, now=now, plans={"finished": "completed"}) == 0
    ids = [message.id for message in read_all(tmp_path)]
    assert len(ids) == 1
    assert re.fullmatch(r"m-[0-9a-f]{8}", ids[0] or "")
    assert run_status(Namespace(now=now.isoformat(), json=True), tmp_path) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["exit_code"] == 0
    assert report["addresses"] == [
        {
            "address": "finished",
            "delivered_not_acked": 0,
            "last_delivery": None,
            "last_delivery_channel": None,
            "oldest_undelivered_age_seconds": 0.0,
            "oldest_unread_age_seconds": None,
            "total": 1,
            "unread": 0,
        }
    ]


def test_relay_planner_accepts_legacy_idless_message_lines(tmp_path: Path) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.relay_plan import plan

    sent = datetime(2026, 1, 1, tzinfo=UTC) - timedelta(minutes=3)
    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "ts": sent.isoformat(),
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "legacy",
            }
        )
        + "\n"
    )
    message = read_all(tmp_path)[0]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = BindingStore(tmp_path)
    marker = store.issue("reader", now=now)
    assert store.redeem(marker, "s", "claude", "/repo", now=now - timedelta(minutes=3))
    result = plan(
        {"messages": [message.to_dict()], "bindings": store.list_bindings()}, now
    )
    assert result["actions"][0]["message_ids"] == [message.id]
