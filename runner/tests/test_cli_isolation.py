from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from store_guard import (
    assert_inbox_unchanged,
    resolve_real_inbox_root,
    snapshot_inbox,
)
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.records.messages import Delivery, NewMessage
from varde_runner.varde_cli import VardeCLI
from varde_runner.workitems import WorkItemStore


def test_real_store_guard_detects_appended_message(tmp_path: Path) -> None:
    fake_inbox = tmp_path / "fake-real-inbox"
    messages = fake_inbox / "messages.jsonl"
    messages.parent.mkdir(parents=True)
    messages.write_text('{"id":"before"}\n', encoding="utf-8")
    before = snapshot_inbox(fake_inbox)
    messages.write_text(
        messages.read_text(encoding="utf-8")
        + '{"id":"vrt-run-1-message","from":"vrt-run-1-builder"}\n'
    )

    with pytest.raises(AssertionError, match="messages.jsonl"):
        assert_inbox_unchanged(fake_inbox, before, run_prefix="vrt-run-1-")


def test_real_store_guard_ignores_unrelated_binding_added_during_run(
    tmp_path: Path,
) -> None:
    fake_inbox = tmp_path / "fake-real-inbox"
    fake_inbox.mkdir()
    bindings = fake_inbox / "bindings"
    bindings.write_text('{"bindings":{}}', encoding="utf-8")
    before = snapshot_inbox(fake_inbox)
    bindings.write_text(
        '{"bindings":{"claude-other-session":{"session_id":"claude-123"}}}',
        encoding="utf-8",
    )

    assert_inbox_unchanged(fake_inbox, before, run_prefix="vrt-run-1-")


def test_real_store_guard_resolves_cli_working_directory(
    monkeypatch, tmp_path: Path
) -> None:
    working = tmp_path / "working-from-cli"
    config = tmp_path / "config"
    env = {
        **os.environ,
        "VARDE_WORKING_DIR": str(working),
        "VARDE_CONFIG_DIR": str(config),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    root = resolve_real_inbox_root(env=env)
    assert root == working / ".cache" / "inbox"


def test_real_store_guard_env_override_wins(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "override-inbox"
    monkeypatch.setenv("VARDE_TEST_REAL_INBOX", str(override))
    assert resolve_real_inbox_root() == override.resolve()


def test_varde_cli_requires_a_safe_working_directory(monkeypatch) -> None:
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    with pytest.raises(ValueError, match="cwd or VARDE_WORKING_DIR"):
        VardeCLI()


def test_varde_cli_reads_ack_status_and_concluded_addresses_read_only(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    state_path = working / ".cache" / "inbox" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"concluded_addresses": ["finished-plan", 3]}),
        encoding="utf-8",
    )
    repository = open_data(working, DataConfig()).messages
    message = repository.append(
        NewMessage(
            "sender",
            "main",
            "info",
            "acknowledged",
            ts="2026-10-24T00:00:00Z",
        )
    )
    repository.record_delivery(
        Delivery(message.id or "", "main", "session", "cli", "delivered", "now")
    )
    repository.ack("main", message.id or "", now="now")
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(working)})

    assert cli.read_message_status() == {
        "messages": [
            {
                "ts": "2026-10-24T00:00:00Z",
                "from": "sender",
                "to": "main",
                "kind": "info",
                "text": "acknowledged",
                "id": message.id,
                "acked": "now",
            }
        ]
    }
    assert cli.read_concluded_addresses() == ["finished-plan"]
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "concluded_addresses": ["finished-plan", 3]
    }


def test_varde_cli_ack_uses_isolated_working_directory(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "ack-argv.json"
    command = bin_dir / "varde"
    command.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "open(os.environ['ACK_ARGV_FILE'], 'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    working = tmp_path / "working"
    working.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "ACK_ARGV_FILE": str(argv_file),
        "VARDE_CONFIG_DIR": str(tmp_path / "config"),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    cli = VardeCLI(cwd=working, env=env)

    assert cli.acknowledge("vrt-message", address="main") == {
        "stdout": "",
        "message_id": "vrt-message",
    }
    assert json.loads(argv_file.read_text(encoding="utf-8")) == [
        "msg",
        "ack",
        "vrt-message",
        "--as",
        "main",
    ]


def test_varde_cli_send_wakes_relay_and_records_liveness(tmp_path: Path) -> None:
    working = tmp_path / "working"
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})

    result = cli.send(
        sender="runner",
        recipient="main",
        kind="info",
        text="hello",
        notes=str(tmp_path / "notes.md"),
    )

    assert result == {"stdout": "", "id": result["id"]}
    assert (working / ".cache/inbox/relay/relay.wake").is_file()
    state = json.loads(
        (working / ".cache/inbox/relay/state.json").read_text(encoding="utf-8")
    )
    event = state["events"][-1]
    assert event["event"] == "send-liveness"
    assert event["message_id"] == result["id"]
    assert event["to"] == "main"


def test_plan_ready_sync_uses_only_the_test_working_store(tmp_path: Path) -> None:
    working = tmp_path / "working"
    env = {
        **os.environ,
        "VARDE_WORKING_DIR": str(working),
        "VARDE_CONFIG_DIR": str(tmp_path / "config"),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }
    cli = VardeCLI(cwd=tmp_path, env=env)
    store = WorkItemStore(tmp_path / "workitems")
    item = store.create("plan-ready-sync", "request", "workspace")
    store.start_planning(
        item.id, f"{os.environ['VARDE_TEST_RUN_PREFIX']}planner-session"
    )
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("plan", encoding="utf-8")
    notes_path = store.item_notes_dir(item.id) / "plan-ready.json"
    notes_path.write_text(
        json.dumps(
            {
                "work_item_event": "plan_ready",
                "plan_path": str(plan_path),
                "asked": "Approve?",
                "why": "Ready",
                "options": [{"label": "Approve", "consequence": "Queue"}],
                "recommendation": "Approve",
                "sources": [],
            }
        ),
        encoding="utf-8",
    )
    address = f"workitem-{item.id[:40]}"
    cli.send(
        sender=address,
        recipient="main",
        kind="needs-user",
        text="Plan ready for approval",
        notes=str(notes_path),
    )
    sent = next(
        message for message in cli.read_messages() if message["from"] == address
    )

    assert store.sync_message(sent, address)
    assert store.get(item.id).state == "ready"
    assert (working / ".cache" / "inbox" / "messages.jsonl").is_file()
    cli._json("msg", "read", "--as", "main")
    acknowledged = cli.acknowledge(sent["id"], address="main")
    assert acknowledged["message_id"] == sent["id"]
