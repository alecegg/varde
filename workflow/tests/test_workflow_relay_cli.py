from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_learn.knowledge import memory
from varde_workflow import cli, relay_wait


def use_working(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    current = working / ".cache/inbox/addresses/mailman/current"
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({"token_id": "token-1"}))
    return working


def test_cli_wait_emits_schema_json_and_sends_diagnostics_to_stderr(
    monkeypatch, tmp_path, capsys
) -> None:
    working = use_working(monkeypatch, tmp_path)
    clock = {"now": datetime(2026, 10, 18, 12, tzinfo=UTC), "polls": 0}

    def poll(delay: float) -> None:
        clock["polls"] += 1
        clock["now"] += timedelta(seconds=11 if clock["polls"] == 1 else delay)

    assert (
        cli.run(
            [
                "msg",
                "relay",
                "--wait",
                "--timeout",
                "12",
                "--as",
                "token-1",
                "--now",
                "2026-10-18T12:00:00+00:00",
            ],
            relay_clock=lambda: clock["now"],
            relay_poll=poll,
        )
        == 0
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "none"
    assert json.loads(captured.out)["waited_s"] == 12
    assert clock["polls"] == 2
    assert captured.err == ""
    assert (working / ".cache/inbox/relay/state.json").exists()
    from varde_workflow.relay_state import planning_state

    assert not any(
        event["event"] == "slept" for event in planning_state(working)["events"]
    )


def test_cli_wait_has_five_second_floor_and_does_not_return_none_early(
    monkeypatch, tmp_path, capsys
) -> None:
    use_working(monkeypatch, tmp_path)
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    clock = {"now": now, "delays": []}

    def poll(delay: float) -> None:
        clock["delays"].append(delay)
        clock["now"] += timedelta(seconds=delay)

    assert (
        cli.run(
            [
                "msg",
                "relay",
                "--wait",
                "--timeout",
                "5",
                "--as",
                "token-1",
                "--now",
                now.isoformat(),
            ],
            relay_clock=lambda: clock["now"],
            relay_poll=poll,
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "none"
    assert result["waited_s"] == 5
    assert sum(clock["delays"]) == 5
    assert len(clock["delays"]) >= 3


def test_cli_rejects_wrong_mailman_token_with_64(monkeypatch, tmp_path, capsys) -> None:
    use_working(monkeypatch, tmp_path)

    assert cli.run(["msg", "relay", "--once", "--as", "wrong"]) == 64
    assert "current mailman token" in capsys.readouterr().err


def test_cli_corrupt_delivery_log_returns_70(monkeypatch, tmp_path, capsys) -> None:
    working = use_working(monkeypatch, tmp_path)
    path = working / ".cache/inbox/deliveries.jsonl"
    path.write_text("not json\n")

    assert cli.run(["msg", "relay", "--once", "--as", "token-1"]) == 70
    assert "error:" in capsys.readouterr().err


def test_cli_confirm_runs_through_cli_router(monkeypatch, tmp_path, capsys) -> None:
    working = use_working(monkeypatch, tmp_path)
    action_dir = working / ".cache/inbox/relay/actions"
    action_dir.mkdir(parents=True)
    (action_dir / "a1.json").write_text(
        json.dumps(
            {
                "action_id": "a1",
                "status": "leased",
                "message_ids": [],
                "address": "worker",
            }
        )
    )

    assert (
        cli.run(
            [
                "msg",
                "relay",
                "confirm",
                "a1",
                "--result",
                "pushed",
                "--now",
                "2026-10-18T12:00:00+00:00",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "confirmed"


def test_msg_send_prints_no_mailman_hint_to_stderr(
    monkeypatch, tmp_path, capsys
) -> None:
    working = use_working(monkeypatch, tmp_path)
    from varde_workflow.slots import add_alias

    add_alias(working, "worker")

    assert (
        cli.run(
            [
                "msg",
                "send",
                "--from",
                "main",
                "--to",
                "worker",
                "--kind",
                "info",
                "hello",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "relay: no mailman waiting (no heartbeat recorded)\n"


def _large_delivered_store(working: Path, now: datetime) -> None:
    from varde_workflow.binding import BindingStore

    store = BindingStore(working)
    for address in ("worker", "main"):
        marker = store.issue(address, supersede=True, now=now - timedelta(hours=1))
        assert store.redeem(
            marker,
            f"{address}-session",
            "claude",
            str(working),
            now=now - timedelta(hours=1),
        )
    inbox = working / ".cache/inbox"
    stamp = (now - timedelta(minutes=30)).isoformat()
    messages = []
    deliveries = []
    for index in range(10_000):
        message_id = f"m-{index:08d}"
        address = "worker" if index < 7_500 else f"unbound-{index}"
        messages.append(
            json.dumps(
                {
                    "id": message_id,
                    "ts": stamp,
                    "from": "sender",
                    "to": address,
                    "kind": "info",
                    "text": "mail",
                }
            )
        )
        if index < 7_500:
            deliveries.extend(
                json.dumps(
                    {
                        "event": event,
                        "message_id": message_id,
                        "reader": address,
                        "at": stamp,
                        "via": "hook",
                    }
                )
                for event in ("delivered", "acked")
            )
    (inbox / "messages.jsonl").write_text("\n".join(messages) + "\n")
    (inbox / "deliveries.jsonl").write_text("\n".join(deliveries) + "\n")


@pytest.mark.slow
def test_once_and_escalate_due_with_delivered_10k_log(
    monkeypatch, tmp_path, capsys
) -> None:
    from varde_workflow.relay_state import escalate_due

    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "files")
    working = use_working(monkeypatch, tmp_path)
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    _large_delivered_store(working, now)

    original_open_data = relay_wait.open_data
    read_sizes: list[int] = []

    def counted_open_data(*args, **kwargs):
        data = original_open_data(*args, **kwargs)
        original_read_all = data.messages.read_all

        def counted_read_all():
            result = original_read_all()
            read_sizes.append(len(result.records))
            return result

        data.messages.read_all = counted_read_all
        return data

    monkeypatch.setattr(relay_wait, "open_data", counted_open_data)

    assert (
        cli.run(["msg", "relay", "--once", "--as", "token-1", "--now", now.isoformat()])
        == 0
    )
    capsys.readouterr()

    assert escalate_due(working, now) == []
    assert len(read_sizes) == 3
    assert read_sizes[0] == 10_000
    assert read_sizes[1] == read_sizes[2]


def test_cli_once_end_renew_timeout_and_negative_context_options(
    monkeypatch, tmp_path, capsys
) -> None:
    working = use_working(monkeypatch, tmp_path)
    now = "2026-10-18T12:00:00+00:00"

    assert cli.run(["msg", "relay", "--once", "--as", "token-1", "--now", now]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "none"
    assert (
        cli.run(["msg", "relay", "--wait", "--timeout", "0", "--as", "token-1"]) == 64
    )
    assert (
        cli.run(["msg", "relay", "--once", "--context-tokens", "-1", "--as", "token-1"])
        == 64
    )

    action_dir = working / ".cache/inbox/relay/actions"
    action_dir.mkdir(parents=True)
    (action_dir / "a2.json").write_text(
        json.dumps(
            {
                "action_id": "a2",
                "status": "leased",
                "expires_at": "2026-10-18T12:05:00+00:00",
            }
        )
    )
    assert cli.run(["msg", "relay", "renew", "a2", "--now", now]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "renewed"
    assert cli.run(["msg", "relay", "end", "--as", "token-1", "--now", now]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ended"


def test_address_refresh_and_relay_once_wakes_refreshed_main(
    monkeypatch, tmp_path, capsys
):
    from varde_workflow.binding import BindingStore
    from varde_workflow.commands.msg import append_message

    working = use_working(monkeypatch, tmp_path)
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    store = BindingStore(working)
    marker = store.issue("main", supersede=True, now=now - timedelta(hours=1))
    assert store.redeem(
        marker, "main-session", "claude", str(working), now=now - timedelta(hours=1)
    )
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "main-session")
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-main")
    assert cli.run(["msg", "address", "refresh"]) == 0
    append_message(
        "worker",
        "main",
        "needs-user",
        "approve",
        working=working,
        now=now - timedelta(minutes=5),
    )

    assert (
        cli.run(["msg", "relay", "--once", "--as", "token-1", "--now", now.isoformat()])
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result["actions"][0]["wake"]["paseo_id"] == "paseo-main"


def test_address_refresh_reports_unbound_and_missing_paseo_id(
    monkeypatch, tmp_path, capsys
):
    working = use_working(monkeypatch, tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "unbound-session")
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-main")

    assert cli.run(["msg", "address", "refresh"]) == 1
    assert "no current binding" in capsys.readouterr().err

    store = __import__(
        "varde_workflow.binding", fromlist=["BindingStore"]
    ).BindingStore(working)
    marker = store.issue("worker", now=datetime.now(UTC))
    assert store.redeem(
        marker, "unbound-session", "claude", str(working), now=datetime.now(UTC)
    )
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    assert cli.run(["msg", "address", "refresh"]) == 1
    assert "PASEO_AGENT_ID" in capsys.readouterr().err


def test_address_refresh_accepts_native_agent_id(monkeypatch, tmp_path):
    from varde_workflow.binding import BindingStore

    working = use_working(monkeypatch, tmp_path)
    store = BindingStore(working)
    marker = store.issue("worker", now=datetime.now(UTC))
    assert store.redeem(
        marker, "native-session", "claude", str(working), now=datetime.now(UTC)
    )
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "native-session")
    monkeypatch.setenv("VARDE_AGENT_ID", "native-agent")
    monkeypatch.setenv("VARDE_HARNESS", "claude-cli")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)

    assert cli.run(["msg", "address", "refresh"]) == 0
    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    assert wake["agent_id"] == "native-agent"
    assert wake["harness"] == "claude-cli"
    assert wake["runner_endpoint"] == "http://127.0.0.1:9000"
