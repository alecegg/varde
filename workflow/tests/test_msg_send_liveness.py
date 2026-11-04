from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace


class DataProxy:
    def __init__(self, data, addresses):
        self.data = data
        self.addresses = addresses

    def __getattr__(self, name):
        return getattr(self.data, name)


class AddressesProxy:
    def __init__(self, repository, **overrides):
        self.repository = repository
        self.overrides = overrides

    def __getattr__(self, name):
        if name in self.overrides:
            return self.overrides[name]
        return getattr(self.repository, name)


def test_send_liveness_warning_includes_heartbeat_age() -> None:
    from varde_workflow.commands.msg import _liveness_warning

    assert _liveness_warning(340, has_token=True) == (
        "relay: no mailman waiting (last heartbeat 340s ago)"
    )
    assert _liveness_warning(None, has_token=False) == (
        "relay: no mailman waiting (no mailman token)"
    )


def test_send_records_mailman_liveness(monkeypatch, tmp_path, capsys) -> None:
    from argparse import Namespace

    from varde_workflow.commands import msg_relay
    from varde_workflow.commands.msg import run
    from varde_workflow.relay_state import load, record
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "worker")

    now = datetime.now(UTC)
    record(
        tmp_path,
        "waiting",
        now=now - timedelta(seconds=340),
        token_id="token",  # noqa: S106 - synthetic relay token for the test fixture
    )
    monkeypatch.setattr(msg_relay, "_mailman_token", lambda _working: "token")
    args = Namespace(
        message_command="send",
        from_address="sender",
        to="worker",
        kind="info",
        text="hello",
        notes=None,
        reply_to=None,
    )

    assert run(args, tmp_path) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "relay: no mailman waiting (last heartbeat 340s ago)\n"
    events = load(tmp_path)["events"]
    sent = next(event for event in events if event["event"] == "send-liveness")
    message_path = tmp_path / ".cache/inbox/messages.jsonl"
    message = json.loads(message_path.read_text().splitlines()[0])
    assert sent == {
        "event": "send-liveness",
        "at": sent["at"],
        "message_id": message["id"],
        "to": "worker",
        "alive": False,
        "token_age_s": 340,
    }


def test_send_without_mailman_token_records_null_age(
    monkeypatch, tmp_path, capsys
) -> None:
    from argparse import Namespace

    from varde_workflow.commands import msg_relay
    from varde_workflow.commands.msg import run
    from varde_workflow.relay_state import load
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "worker")

    monkeypatch.setattr(msg_relay, "_mailman_token", lambda _working: None)
    args = Namespace(
        message_command="send",
        from_address="sender",
        to="worker",
        kind="info",
        text="hello",
        notes=None,
        reply_to=None,
    )

    assert run(args, tmp_path) == 0
    assert capsys.readouterr().err == ("relay: no mailman waiting (no mailman token)\n")
    sent = next(
        event for event in load(tmp_path)["events"] if event["event"] == "send-liveness"
    )
    assert sent["alive"] is False
    assert sent["token_age_s"] is None


def test_send_liveness_is_best_effort_for_malformed_heartbeat(
    monkeypatch, tmp_path, capsys
) -> None:
    from argparse import Namespace

    from varde_data.open import open_data
    from varde_workflow.commands import msg_relay
    from varde_workflow.commands.msg import run
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "worker")

    monkeypatch.setattr(msg_relay, "_mailman_token", lambda _working: "token")
    original_open_data = open_data

    def open_with_malformed_heartbeat(working, config):
        data = original_open_data(working, config)
        return DataProxy(
            data,
            AddressesProxy(
                data.addresses,
                relay_snapshot=lambda: SimpleNamespace(
                    events=({"token_id": "token", "at": "bad"},)
                ),
            ),
        )

    monkeypatch.setattr("varde_data.open.open_data", open_with_malformed_heartbeat)
    args = Namespace(
        message_command="send",
        from_address="sender",
        to="worker",
        kind="info",
        text="hello",
        notes=None,
        reply_to=None,
    )

    assert run(args, tmp_path) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error:" not in captured.err


def test_send_liveness_record_failure_does_not_fail_send(
    monkeypatch, tmp_path, capsys
) -> None:
    from argparse import Namespace

    from varde_workflow import relay_state
    from varde_workflow.commands import msg_relay
    from varde_workflow.commands.msg import run
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "worker")

    monkeypatch.setattr(msg_relay, "_mailman_token", lambda _working: None)

    def fail_record(*_args, **_kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(relay_state, "record", fail_record)
    args = Namespace(
        message_command="send",
        from_address="sender",
        to="worker",
        kind="info",
        text="hello",
        notes=None,
        reply_to=None,
    )

    assert run(args, tmp_path) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_send_records_alive_true_without_warning(monkeypatch, tmp_path, capsys) -> None:
    from argparse import Namespace

    from varde_data.open import open_data
    from varde_workflow import relay_state
    from varde_workflow.commands import msg_relay
    from varde_workflow.commands.msg import run
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "worker")

    monkeypatch.setattr(msg_relay, "_mailman_token", lambda _working: "token")
    original_open_data = open_data

    def open_with_live_mailman(working, config):
        data = original_open_data(working, config)
        return DataProxy(
            data,
            AddressesProxy(data.addresses, mailman_alive=lambda *_args: True),
        )

    monkeypatch.setattr("varde_data.open.open_data", open_with_live_mailman)
    args = Namespace(
        message_command="send",
        from_address="sender",
        to="worker",
        kind="info",
        text="hello",
        notes=None,
        reply_to=None,
    )

    assert run(args, tmp_path) == 0
    assert capsys.readouterr().err == ""
    sent = next(
        event
        for event in relay_state.load(tmp_path)["events"]
        if event["event"] == "send-liveness"
    )
    assert sent["alive"] is True


def test_token_age_s_handles_missing_token_events_and_clock_skew() -> None:
    from varde_workflow.send_liveness import _token_age_s

    now = datetime(2026, 1, 1, tzinfo=UTC)
    other_token = {
        "token_id": "other",
        "at": (now - timedelta(seconds=20)).isoformat(),
    }
    assert _token_age_s([other_token], None, now) is None
    assert _token_age_s([], "token", now) is None
    assert _token_age_s([other_token], "token", now) is None
    future_event = {
        "token_id": "token",
        "at": (now + timedelta(seconds=20)).isoformat(),
    }
    assert _token_age_s([future_event], "token", now) == 0
