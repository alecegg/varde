from __future__ import annotations

from datetime import UTC, datetime, timedelta

from varde_data.records.addresses import AddressSlot
from varde_workflow.urgent import urgent_send_cause

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


def test_urgent_sender_allowlist():
    assert urgent_send_cause("main", "plan-a-builder", [], NOW) is None
    assert urgent_send_cause("plan-a-orchestrator", "plan-a-builder", [], NOW) is None
    assert (
        urgent_send_cause("plan-b-reviewer", "plan-a-builder", [], NOW)
        == "unauthorized sender"
    )
    assert (
        urgent_send_cause("plan-a-builder", "plan-a-builder", [], NOW)
        == "unauthorized sender"
    )
    slots = [AddressSlot("orchestrator-1", ("plan-a",))]
    assert urgent_send_cause("orchestrator-1", "plan-a-builder", [], NOW, slots) is None


def test_urgent_rate_limits_are_scoped_and_windowed():
    events = [
        {
            "event": "urgent",
            "reader": "plan-a-builder",
            "at": (NOW - timedelta(minutes=1)).isoformat(),
        }
        for _ in range(3)
    ]
    assert (
        urgent_send_cause("main", "plan-a-builder", events, NOW)
        == "recipient rate limit exceeded"
    )
    old = [
        {**event, "at": (NOW - timedelta(minutes=11)).isoformat()} for event in events
    ]
    assert urgent_send_cause("main", "plan-a-builder", old, NOW) is None
    global_events = [
        {"event": "urgent", "reader": f"recipient-{index}", "at": NOW.isoformat()}
        for index in range(10)
    ]
    assert (
        urgent_send_cause("main", "plan-a-builder", global_events, NOW)
        == "global urgent rate limit exceeded"
    )


def test_send_urgent_records_marker_for_relay(tmp_path, monkeypatch):
    from varde_workflow.cli import _parser
    from varde_workflow.commands import msg
    from varde_workflow.inbox import delivery_events, read_all
    from varde_workflow.recipients import Resolved

    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setattr(
        msg,
        "_resolve_recipient",
        lambda _name, _working: Resolved("plan-a-builder", True, True),
    )
    args = _parser().parse_args(
        [
            "msg",
            "send",
            "--from",
            "main",
            "--to",
            "plan-a-builder",
            "--kind",
            "info",
            "--urgent",
            "urgent text",
        ]
    )

    assert msg.run(args, working) == 0
    sent = read_all(working)[0]
    marker = next(
        event for event in delivery_events(working) if event["event"] == "urgent"
    )
    assert marker["message_id"] == sent.id
    assert marker["reader"] == "plan-a-builder"


def test_urgent_send_rejections_do_not_queue(tmp_path, monkeypatch, capsys):
    from varde_workflow.cli import _parser
    from varde_workflow.commands import msg
    from varde_workflow.inbox import append_message, read_all, record_relay_event
    from varde_workflow.recipients import Resolved

    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setattr(
        msg,
        "_resolve_recipient",
        lambda name, _working: Resolved(name, True, True),
    )
    now = datetime.now(UTC)

    cases = [
        ("plan-a-builder", "plan-a-builder", [], "unauthorized sender"),
        (
            "main",
            "plan-a-builder",
            ["plan-a-builder"] * 3,
            "recipient rate limit exceeded",
        ),
        (
            "main",
            "plan-a-builder",
            [f"plan-{index}-builder" for index in range(10)],
            "global urgent rate limit exceeded",
        ),
    ]
    for index, (sender, recipient, previous, cause) in enumerate(cases):
        case_working = working / f"case-{index}"
        case_working.mkdir()
        monkeypatch.chdir(case_working)

        for item in previous:
            message = append_message(
                "main", item, "info", "previous", working=case_working
            )
            record_relay_event(
                case_working,
                message.id or "",
                item,
                "urgent",
                now=now - timedelta(minutes=1),
                sender="main",
            )
        before = len(read_all(case_working))
        args = _parser().parse_args(
            [
                "msg",
                "send",
                "--from",
                sender,
                "--to",
                recipient,
                "--kind",
                "info",
                "--urgent",
                "rejected",
            ]
        )

        assert msg.run(args, case_working) == 1
        assert cause in capsys.readouterr().err
        assert len(read_all(case_working)) == before


def test_paseo_notice_resolves_binding_under_slot_alias(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from varde_data.records.addresses import AddressSlot
    from varde_workflow.commands.msg import _is_paseo_recipient

    addresses = SimpleNamespace(
        slots=lambda: (AddressSlot("plan-a-builder", ("builder-alias",)),),
        list_bindings=lambda: (
            SimpleNamespace(address="builder-alias", harness="paseo", extra={}),
        ),
        resolve_alias=lambda name: (
            "plan-a-builder" if name in {"plan-a-builder", "builder-alias"} else name
        ),
        live_addresses=lambda _now: frozenset({"builder-alias"}),
    )
    monkeypatch.setattr(
        "varde_data.open.open_data",
        lambda *_args, **_kwargs: SimpleNamespace(addresses=addresses),
    )

    assert _is_paseo_recipient("plan-a-builder", tmp_path)
