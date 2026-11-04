from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from varde_data.addresses import open_addresses
from varde_data.backends.files.messages import FilesMessages
from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import NewMessage, RelayEvent
from varde_data.relay import RelayService, Stopped

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _service(root):
    return RelayService(
        open_addresses(root, "files"),
        FilesMessages(root),
        now=lambda: NOW,
        instance_id="paseo-fixed:12345",
    )


def _bind(addresses, name, now=NOW):
    token = addresses.issue(name, now=now)
    marker = token
    assert addresses.redeem(
        marker, f"{name}-session", "codex", ReaderContext(cwd="."), now=now
    )


def test_once_leases_due_message_and_confirm_records_delivery(tmp_path):
    service = _service(tmp_path)
    _bind(service.addresses, "reader")
    service.messages.append(
        NewMessage(
            "sender",
            "reader",
            "info",
            "due",
            ts=(NOW - timedelta(minutes=3)).isoformat(),
        )
    )
    response = service.once("mailman-token")
    assert response["status"] == "actions"
    action = response["actions"][0]
    assert service.confirm(action["action_id"], "pushed")["status"] == "confirmed"
    assert service.confirm(action["action_id"], "pushed")["status"] == "duplicate"


def test_failed_confirm_persists_reason_in_delivery(tmp_path):
    service = _service(tmp_path)
    _bind(service.addresses, "reader")
    message = service.messages.append(
        NewMessage(
            "sender",
            "reader",
            "info",
            "due",
            ts=(NOW - timedelta(minutes=3)).isoformat(),
        )
    )
    action = service.once("mailman-token")["actions"][0]

    service.confirm(action["action_id"], "failed", reason="provider timeout")

    delivery = next(
        row for row in service.messages.deliveries() if row.message_id == message.id
    )
    assert delivery.event == "failed"
    assert delivery.reason == "provider timeout"


def test_wait_stop_is_checked_before_leasing(tmp_path):
    service = _service(tmp_path)
    _bind(service.addresses, "reader")
    service.messages.append(
        NewMessage("sender", "reader", "blocked", "due", ts=NOW.isoformat())
    )
    with pytest.raises(Stopped):
        service.wait("mailman-token", 10, stop=lambda: True)
    assert service.addresses.relay_snapshot().leases == ()


def test_end_and_renew_delegate_to_address_repository(tmp_path):
    service = _service(tmp_path)
    service.addresses.lease_actions(
        ({"to": "reader", "message_ids": ["m-00000001"]},), "t", NOW
    )
    action = service.addresses.relay_snapshot().leases[0]
    assert service.renew(action.action_id, NOW + timedelta(seconds=1))
    service.end("t", NOW)
    assert service.addresses.relay_snapshot().events[-1]["event"] == "ended"


def test_escalate_due_records_urgent_message_once(tmp_path):
    service = _service(tmp_path)
    message = service.messages.append(
        NewMessage(
            "sender",
            "unbound",
            "needs-user",
            "escalate",
            ts=(NOW - timedelta(minutes=11)).isoformat(),
        )
    )

    assert message.id is not None
    assert service.escalate_due(NOW) == [message.id]
    assert service.escalate_due(NOW) == []
    assert any(
        row.from_ == "relay" and message.id in row.text
        for row in service.messages.read_all().records
    )
    notice = next(
        row
        for row in service.messages.read_all().records
        if row.from_ == "relay" and row.to == "main" and message.id in row.text
    )
    assert notice.kind == "info-failure"


def test_undelivered_deadline_notice_names_failure_reason_once(tmp_path):
    service = _service(tmp_path)
    _bind(service.addresses, "reader")
    sent = NOW - timedelta(minutes=10) + timedelta(seconds=1)
    message = service.messages.append(
        NewMessage("sender", "reader", "info", "deadline", ts=sent.isoformat())
    )
    service.messages.record_relay_event(
        RelayEvent(
            message.id or "",
            "reader",
            "failed",
            (NOW - timedelta(minutes=9)).isoformat(),
            reason="provider timeout",
        )
    )

    assert service.escalate_due(NOW) == []
    assert service.escalate_due(NOW + timedelta(seconds=1)) == [message.id]
    assert service.escalate_due(NOW + timedelta(seconds=2)) == []
    notice = next(
        row
        for row in service.messages.read_all().records
        if row.kind == "info-failure" and (message.id or "") in row.text
    )
    assert "no-receipt (provider timeout)" in notice.text


def test_escalate_due_resolves_slot_alias_before_short_deadline(tmp_path):
    service = _service(tmp_path)
    service.addresses.add_alias("worker", "old-worker")
    _bind(service.addresses, "worker")
    message = service.messages.append(
        NewMessage(
            "sender",
            "old-worker",
            "info",
            "aliased recipient",
            ts=(NOW - timedelta(minutes=3)).isoformat(),
        )
    )

    assert service.escalate_due(NOW) == []
    assert not any(
        row.kind == "info-failure" and (message.id or "") in row.text
        for row in service.messages.read_all().records
    )


@pytest.mark.parametrize(
    ("recipient", "registered", "bound", "event", "expected"),
    (
        ("legacy-unknown", False, False, None, "unresolvable"),
        ("plan-a-builder", True, False, None, "no-holder"),
        ("worker", True, False, None, "unbound"),
        ("worker", True, True, "skipped-busy", "busy (recipient busy)"),
        ("worker", True, True, "failed", "no-receipt (provider timeout)"),
    ),
)
def test_escalation_notice_names_each_cause(
    tmp_path, recipient, registered, bound, event, expected
):
    service = _service(tmp_path)
    if registered:
        service.addresses.add_alias(recipient)
    if bound:
        _bind(service.addresses, recipient)
    message = service.messages.append(
        NewMessage(
            "sender",
            recipient,
            "info",
            "cause test",
            ts=(NOW - timedelta(minutes=11)).isoformat(),
        )
    )
    if event:
        service.messages.record_relay_event(
            RelayEvent(
                message.id or "",
                recipient,
                event,
                NOW.isoformat(),
                reason=(
                    "recipient busy" if event == "skipped-busy" else "provider timeout"
                ),
            )
        )

    assert service.escalate_due(NOW) == [message.id]
    notice = next(
        row
        for row in service.messages.read_all().records
        if row.kind == "info-failure" and (message.id or "") in row.text
    )
    assert expected in notice.text


def test_undelivered_backlog_caps_notices_and_skips_closed_addresses(tmp_path):
    service = _service(tmp_path)
    service.messages.mark_concluded("concluded")
    service.addresses.retire(["retired"], [], NOW)
    messages = [
        service.messages.append(
            NewMessage(
                "sender",
                "reader",
                "info",
                f"backlog {index}",
                ts=(NOW - timedelta(minutes=11 + index)).isoformat(),
            )
        )
        for index in range(8)
    ]
    closed = [
        service.messages.append(
            NewMessage(
                "sender",
                address,
                "info",
                "closed",
                ts=(NOW - timedelta(hours=1)).isoformat(),
            )
        )
        for address in ("concluded", "retired")
    ]

    escalated = service.escalate_due(NOW)
    notices = [
        row
        for row in service.messages.read_all().records
        if row.from_ == "relay" and row.to == "main" and row.kind == "info-failure"
    ]
    individual = [row for row in notices if row.text.startswith("Message m-")]

    assert escalated == [row.id for row in messages]
    assert len(individual) == 5
    assert len(notices) == 6
    assert "3 messages" in next(row.text for row in notices if row not in individual)
    assert all(
        (row.id or "") in " ".join(item.text for item in individual)
        for row in messages[:5]
    )
    assert all(
        (row.id or "") not in " ".join(item.text for item in individual)
        for row in messages[5:]
    )
    assert all(row.id not in escalated for row in closed)
    assert service.escalate_due(NOW) == []


def test_escalate_due_skips_malformed_message_timestamp(tmp_path):
    service = _service(tmp_path)
    message = service.messages.append(
        NewMessage("sender", "reader", "info", "bad time", ts="garbage")
    )

    assert service.escalate_due(NOW) == []
    response = service.once("mailman-token")
    assert all(item["message_id"] != message.id for item in response["escalations"])


def test_escalate_due_does_not_escalate_claimed_message(tmp_path):
    service = _service(tmp_path)
    message = service.messages.append(
        NewMessage(
            "sender",
            "reader",
            "info",
            "delivered",
            ts=(NOW - timedelta(minutes=20)).isoformat(),
        )
    )
    service.messages.record_relay_event(
        RelayEvent(
            message.id or "",
            "reader",
            "delivered",
            NOW.isoformat(),
            via="hook",
        )
    )

    assert service.escalate_due(NOW) == []


def test_wait_returns_superseded_mailman_without_leasing(tmp_path):
    service = _service(tmp_path)
    _bind(service.addresses, "mailman")
    first = service.addresses.current_token("mailman")
    replacement = service.addresses.issue(
        "mailman", now=NOW + timedelta(seconds=1), supersede=True
    )
    assert service.addresses.redeem(
        replacement,
        "mailman-next",
        "codex",
        ReaderContext(cwd="."),
        now=NOW + timedelta(seconds=1),
    )
    assert first is not None
    assert first != service.addresses.current_token("mailman")

    response = service.wait(first, 10, poll=lambda _seconds: None)

    assert response["status"] == "superseded"
    assert service.addresses.relay_snapshot().leases == ()


def test_wait_returns_superseded_when_current_pointer_is_missing(tmp_path):
    service = _service(tmp_path)
    _bind(service.addresses, "mailman")
    token = service.addresses.current_token("mailman")
    assert token is not None
    (tmp_path / ".cache/inbox/addresses/mailman/current").unlink()

    response = service.wait(token, 10, poll=lambda _seconds: None)

    assert response["status"] == "superseded"
    assert service.addresses.relay_snapshot().events[-1]["event"] == "ended"
    assert service.addresses.relay_snapshot().leases == ()


def test_wait_uses_due_based_polling_and_returns_at_deadline(tmp_path):
    tick = [NOW]
    mono = [0.0]
    delays = []
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
        instance_id="paseo-fixed:12345",
    )
    _bind(service.addresses, "mailman")
    token = service.addresses.current_token("mailman")
    assert token is not None

    def poll(seconds):
        delays.append(seconds)
        tick[0] += timedelta(seconds=seconds)
        mono[0] += seconds

    result = service.wait(token, 5, poll=poll)

    assert delays == [2, 2, 1]
    assert result["now"] == "2026-10-22T12:00:05Z"
    assert result["waited_s"] == 5
    assert service.addresses.relay_snapshot().cycles[token] == 1


def test_idle_wait_backs_off_until_state_changes(tmp_path):
    tick = [NOW]
    mono = [0.0]
    delays = []
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
    )
    _bind(service.addresses, "mailman")
    token = service.addresses.current_token("mailman")
    assert token is not None

    def poll(seconds):
        delays.append(seconds)
        tick[0] += timedelta(seconds=seconds)
        mono[0] += seconds

    service.wait(token, 34, poll=poll)

    assert delays == [2, 2, 4, 8, 8, 8, 2]
    assert all(
        event.get("event") != "slept"
        for event in service.addresses.relay_snapshot().events
    )


def test_idle_wait_delivers_mail_within_eight_seconds_of_arrival(tmp_path):
    tick = [NOW]
    mono = [0.0]
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
    )
    _bind(service.addresses, "reader")
    _bind(service.addresses, "mailman")
    token = service.addresses.current_token("mailman")
    assert token is not None
    arrival: list[float | None] = [None]

    def poll(seconds):
        if mono[0] == 16:
            arrival[0] = mono[0]
            service.messages.append(
                NewMessage(
                    "sender",
                    "reader",
                    "info",
                    "wake",
                    ts=(tick[0] - timedelta(minutes=3)).isoformat(),
                )
            )
        tick[0] += timedelta(seconds=seconds)
        mono[0] += seconds

    result = service.wait(token, 40, poll=poll)

    assert arrival[0] is not None
    assert result["status"] == "actions"
    assert mono[0] - arrival[0] <= 8


def test_wait_polls_until_next_planner_due_time(tmp_path):
    tick = [NOW]
    mono = [0.0]
    delays = []
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
        instance_id="paseo-fixed:12345",
    )
    _bind(service.addresses, "mailman")
    reader_seen = NOW - timedelta(seconds=119)
    _bind(service.addresses, "reader", reader_seen)
    service.messages.append(
        NewMessage("sender", "reader", "info", "due soon", ts=reader_seen.isoformat())
    )
    token = service.addresses.current_token("mailman")
    assert token is not None

    def poll(seconds):
        delays.append(seconds)
        tick[0] += timedelta(seconds=seconds)
        mono[0] += seconds

    result = service.wait(token, 5, poll=poll)

    assert delays == [1]
    assert result["status"] == "actions"
    assert result["now"] == "2026-10-22T12:00:01Z"


def test_wait_records_workflow_gap_s_field(tmp_path, monkeypatch):
    tick = [NOW]
    mono = [0.0]
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
        instance_id="paseo-fixed:12345",
    )
    _bind(service.addresses, "mailman")
    token = service.addresses.current_token("mailman")
    assert token is not None
    monkeypatch.setattr(
        service,
        "_state",
        lambda: {"messages": [], "events": [], "leases": [{"action_id": "a"}]},
    )
    first = True

    def poll(seconds):
        nonlocal first
        elapsed = 11 if first else seconds
        first = False
        tick[0] += timedelta(seconds=elapsed)
        mono[0] += elapsed

    service.wait(token, 15, poll=poll)

    slept = [
        event
        for event in service.addresses.relay_snapshot().events
        if event.get("event") == "slept"
    ]
    assert slept[0]["gap_s"] == 11
    assert "gap_seconds" not in slept[0]


def test_wait_replans_after_repository_version_and_wake_change(tmp_path):
    tick = [NOW]
    mono = [0.0]
    delays = []
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
        instance_id="paseo-fixed:12345",
    )
    _bind(service.addresses, "mailman")
    _bind(service.addresses, "reader")
    token = service.addresses.current_token("mailman")
    assert token is not None

    def poll(seconds):
        delays.append(seconds)
        service.messages.append(
            NewMessage(
                "sender",
                "reader",
                "blocked",
                "arrived",
                ts=(NOW - timedelta(minutes=3)).isoformat(),
            )
        )
        service.addresses.touch_wake()
        tick[0] += timedelta(seconds=seconds)
        mono[0] += seconds

    result = service.wait(token, 10, poll=poll)

    assert delays == [2]
    assert result["status"] == "actions"
    assert result["actions"][0]["to"] == "reader"


def test_wait_resolves_repeated_addresses_once_per_replan(tmp_path, monkeypatch):
    service = _service(tmp_path)
    marker = service.addresses.issue("mailman", now=NOW)
    assert service.addresses.redeem(
        marker, "runner-test", "codex", ReaderContext(cwd="."), now=NOW
    )
    token = service.addresses.current_token("mailman")
    assert token is not None
    for index in range(40):
        service.messages.append(
            NewMessage(
                "sender", "reader", "info", f"message-{index}", ts=NOW.isoformat()
            )
        )

    calls = {"slots": 0, "resolve_alias": 0}
    addresses = cast("Any", service.addresses)
    invoke = addresses._invoke

    def counted_invoke(name, *args, **kwargs):
        if name in calls:
            calls[name] += 1
        return invoke(name, *args, **kwargs)

    monkeypatch.setattr(addresses, "_invoke", counted_invoke)

    def stop_after_replan(_delay):
        raise RuntimeError("stop after replan")

    with pytest.raises(RuntimeError, match="stop after replan"):
        service.wait(token, 10, poll=stop_after_replan)

    assert calls == {"slots": 2, "resolve_alias": 3}


def test_idle_wait_reloads_slots_only_after_heartbeat_wakes(tmp_path, monkeypatch):
    tick = [NOW]
    mono = [0.0]
    service = RelayService(
        open_addresses(tmp_path, "files"),
        FilesMessages(tmp_path),
        now=lambda: tick[0],
        monotonic=lambda: mono[0],
    )
    _bind(service.addresses, "mailman")
    token = service.addresses.current_token("mailman")
    assert token is not None

    calls = {"slots": 0}
    addresses = cast("Any", service.addresses)
    invoke = addresses._invoke

    def counted_invoke(name, *args, **kwargs):
        if name == "slots":
            calls[name] += 1
        return invoke(name, *args, **kwargs)

    monkeypatch.setattr(addresses, "_invoke", counted_invoke)

    def advance(seconds):
        tick[0] += timedelta(seconds=seconds)
        mono[0] += seconds

    result = service.wait(token, 65, poll=advance)

    assert result["status"] == "none"
    assert calls["slots"] == 6
