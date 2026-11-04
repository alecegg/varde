from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from varde.glue.inbox_hook import prompt_inbox
from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import append_message
from varde_workflow.inbox import delivery_events
from varde_workflow.relay_state import lease_actions


def _environment(monkeypatch, working):
    monkeypatch.chdir(working)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(working / "config"))
    monkeypatch.setenv("HOME", str(working / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(working / "xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(working / "data"))
    monkeypatch.delenv("VARDE_ADDRESS", raising=False)


def _receipt_case(tmp_path, monkeypatch, *, count=1, lease_for=timedelta(minutes=5)):
    _environment(monkeypatch, tmp_path)
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    binding = BindingStore(tmp_path)
    token = binding.issue("worker", now=now)
    assert binding.redeem(token, "session", "claude", str(tmp_path), now=now)
    messages = [
        append_message(
            "sender", "worker", "info", f"mail {index}", working=tmp_path, now=now
        )
        for index in range(count)
    ]
    action = lease_actions(
        tmp_path,
        [{"to": "worker", "message_ids": [message.id for message in messages]}],
        "mailman-token",
        now,
        lease_for=lease_for,
    )[0]
    return now, messages, action


def _prompt(prompt, now):
    return prompt_inbox(
        "claude",
        json.dumps({"session_id": "session", "prompt": prompt}).encode(),
        now=now,
        banner_enabled=False,
    )


@pytest.mark.parametrize("line", [1, 5])
def test_receipt_on_first_and_fifth_line_delivers_without_ack(
    tmp_path, monkeypatch, line
):
    now, messages, action = _receipt_case(tmp_path, monkeypatch)
    marker = f"[varde-delivery: {action['action_id']} worker]"
    prompt = marker if line == 1 else "one\ntwo\nthree\nfour\n" + marker

    assert _prompt(prompt, now) == []
    assert _prompt(prompt, now) == []
    events = delivery_events(tmp_path)
    assert [(event["event"], event["via"]) for event in events] == [
        ("delivered", "receipt")
    ]
    assert events[0]["message_id"] == messages[0].id
    assert "acked" not in {event["event"] for event in events}


def test_prompt_hook_without_store_is_noop_and_does_not_create_it(
    tmp_path, monkeypatch
):
    _environment(monkeypatch, tmp_path)
    payload = json.dumps({"session_id": "session", "prompt": "hello"}).encode()

    assert prompt_inbox("claude", payload, banner_enabled=False) == []
    assert not (tmp_path / ".cache" / "inbox").exists()


def test_receipt_requires_own_line_in_first_five_lines(tmp_path, monkeypatch):
    now, _, action = _receipt_case(tmp_path, monkeypatch)
    marker = f"[varde-delivery: {action['action_id']} worker]"

    assert _prompt("one\ntwo\nthree\nfour\nfive\n" + marker, now)
    _prompt("prefix " + marker, now)
    assert "receipt" not in {event["via"] for event in delivery_events(tmp_path)}


def test_wrong_address_records_misdelivered(tmp_path, monkeypatch):
    now, messages, action = _receipt_case(tmp_path, monkeypatch)

    assert _prompt(f"[varde-delivery: {action['action_id']} other]", now)
    event = delivery_events(tmp_path)[0]
    assert (event["event"], event["reader"], event["message_id"]) == (
        "misdelivered",
        "worker",
        messages[0].id,
    )
    assert "receipt" not in {
        item["via"]
        for item in delivery_events(tmp_path)
        if item["event"] == "delivered"
    }


def test_unknown_expired_and_unbound_receipts_are_noops(tmp_path, monkeypatch):
    now, _, action = _receipt_case(
        tmp_path, monkeypatch, lease_for=timedelta(minutes=1)
    )

    assert _prompt("[varde-delivery: unknown worker]", now)
    _prompt(
        f"[varde-delivery: {action['action_id']} worker]", now + timedelta(minutes=2)
    )
    assert "receipt" not in {event["via"] for event in delivery_events(tmp_path)}
    from varde_workflow.relay_state import load

    noops = [
        event
        for event in load(tmp_path).get("events", [])
        if event["event"] == "receipt-noop"
    ]
    assert {(event["action_id"], event["reason"]) for event in noops} == {
        ("unknown", "unknown"),
        (action["action_id"], "expired"),
    }

    # An issued-but-unredeemed session cannot turn a prompt into a receipt.
    payload = json.dumps(
        {
            "session_id": "unbound",
            "prompt": f"[varde-delivery: {action['action_id']} worker]",
        }
    ).encode()
    assert prompt_inbox("claude", payload, now=now, banner_enabled=False) == []
    assert "receipt" not in {event["via"] for event in delivery_events(tmp_path)}


def test_expired_wrong_address_is_logged_once_per_message_and_session(
    tmp_path, monkeypatch
):
    now, messages, action = _receipt_case(
        tmp_path, monkeypatch, lease_for=timedelta(minutes=1)
    )
    marker = f"[varde-delivery: {action['action_id']} other]"
    _prompt(marker, now + timedelta(minutes=2))
    _prompt(marker, now + timedelta(minutes=2))
    misdelivered = [
        event for event in delivery_events(tmp_path) if event["event"] == "misdelivered"
    ]
    assert len(misdelivered) == 1
    assert misdelivered[0]["message_id"] == messages[0].id


def test_hook_delivery_wins_and_receipt_does_not_print_twice(tmp_path, monkeypatch):
    now, messages, action = _receipt_case(tmp_path, monkeypatch)
    first = _prompt("ordinary prompt", now)
    assert first == [f"inbox: {messages[0].line()}"]

    assert _prompt(f"[varde-delivery: {action['action_id']} worker]", now) == []
    assert [event["event"] for event in delivery_events(tmp_path)] == [
        "delivered",
        "acked",
    ]


def test_receipt_banner_path_handles_ten_thousand_log_lines(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    store = BindingStore(tmp_path)
    token = store.issue("main", supersede=True, now=now)
    assert store.redeem(token, "main-session", "claude", str(tmp_path), now=now)
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    messages = []
    deliveries = []
    for index in range(10_000):
        message_id = f"m-{index:08d}"
        address = "worker" if index < 7_500 else f"unbound-{index}"
        messages.append(
            json.dumps(
                {
                    "id": message_id,
                    "ts": "2026-10-18T11:00:00Z",
                    "from": "sender",
                    "to": address,
                    "kind": "info",
                    "text": "log",
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
                        "at": "2026-10-18T11:00:00Z",
                        "via": "hook",
                    }
                )
                for event in ("delivered", "acked")
            )
    (inbox / "messages.jsonl").write_text("\n".join(messages) + "\n")
    (inbox / "deliveries.jsonl").write_text("\n".join(deliveries) + "\n")
    payload = json.dumps({"session_id": "main-session", "prompt": "prompt"}).encode()

    # CPU time, not wall clock: load from parallel suites must not fail the guard.
    started = time.process_time()
    prompt_inbox("claude", payload, now=now, banner_enabled=True)

    assert time.process_time() - started < 3
