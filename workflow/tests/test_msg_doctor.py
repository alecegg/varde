from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from varde_data.records.addresses import AddressSlot
from varde_workflow.commands.msg_doctor import aggregate_doctor, run
from varde_workflow.inbox import append_message

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("cause", "address", "slots", "bindings", "event"),
    [
        (
            "unresolvable",
            "ghost",
            (),
            {"ghost"},
            {"event": "target-gone", "reason": "unresolvable"},
        ),
        ("unbound", "custom", (AddressSlot("custom"),), set(), None),
        (
            "busy",
            "plan-a-reviewer",
            (AddressSlot("plan-a-reviewer"),),
            {"plan-a-reviewer"},
            {"event": "skipped-busy", "reason": "busy"},
        ),
        (
            "no-receipt",
            "plan-b-builder",
            (AddressSlot("plan-b-builder"),),
            {"plan-b-builder"},
            None,
        ),
        (
            "no-holder",
            "plan-a-builder",
            (AddressSlot("plan-a-builder"),),
            set(),
            None,
        ),
    ],
)
def test_doctor_overdue_live_recipient_exits_one(
    cause, address, slots, bindings, event
) -> None:
    sent = (NOW - timedelta(minutes=12)).isoformat()
    deliveries = (
        [{"message_id": "message", "reader": address, "at": sent, **event}]
        if event
        else []
    )
    report = aggregate_doctor(
        [{"id": "message", "to": address, "kind": "info", "ts": sent}],
        deliveries,
        {"events": []},
        {
            "slots": slots,
            "bindings": bindings,
            "live_addresses": {address},
            "excluded_addresses": set(),
        },
        NOW,
    )

    assert report["overdue_by_cause"] == {cause: 1}
    assert report["exit_code"] == 1


def test_doctor_uses_relay_deadlines_and_exclusions() -> None:
    messages = [
        {
            "id": "main-old",
            "to": "main",
            "kind": "info",
            "ts": (NOW - timedelta(minutes=30)).isoformat(),
        },
        {
            "id": "ghost-five-minutes",
            "to": "ghost",
            "kind": "info",
            "ts": (NOW - timedelta(minutes=5)).isoformat(),
        },
        {
            "id": "retired-old",
            "to": "retired-builder",
            "kind": "info",
            "ts": (NOW - timedelta(minutes=30)).isoformat(),
        },
        {
            "id": "concluded-old",
            "to": "concluded-builder",
            "kind": "info",
            "ts": (NOW - timedelta(minutes=30)).isoformat(),
        },
    ]
    report = aggregate_doctor(
        messages,
        [],
        {"events": []},
        {
            "slots": (
                AddressSlot("retired-builder"),
                AddressSlot("concluded-builder"),
            ),
            "bindings": set(),
            "live_addresses": set(),
            "excluded_addresses": {"retired-builder"},
        },
        NOW,
    )

    assert report["overdue_by_cause"] == {"no-holder": 1, "unresolvable": 1}
    assert report["exit_code"] == 0


def test_doctor_hides_retired_backlog_and_keeps_live_recipient() -> None:
    sent = (NOW - timedelta(minutes=30)).isoformat()
    report = aggregate_doctor(
        [
            {"id": "retired", "to": "old-worker", "kind": "info", "ts": sent},
            {"id": "live", "to": "builder", "kind": "info", "ts": sent},
            {"id": "main", "to": "main", "kind": "info", "ts": sent},
        ],
        [],
        {"events": []},
        {
            "slots": (AddressSlot("old-worker"), AddressSlot("builder")),
            "bindings": {"builder", "old-worker"},
            "live_addresses": {"builder", "old-worker"},
            "excluded_addresses": {"old-worker", "main"},
        },
        NOW,
    )

    assert [row["address"] for row in report["recipients"]] == [
        "builder",
        "main",
        "old-worker",
    ]


def test_doctor_aggregates_liveness_and_unread_urgent() -> None:
    sent = (NOW - timedelta(minutes=12)).isoformat()
    report = aggregate_doctor(
        [
            {
                "id": "urgent-unread",
                "to": "plan-b-builder",
                "kind": "blocked",
                "ts": sent,
            }
        ],
        [
            {
                "message_id": "urgent-unread",
                "reader": "plan-b-builder",
                "event": "urgent",
                "at": sent,
            },
            {
                "message_id": "urgent-unread",
                "reader": "plan-b-builder",
                "event": "delivered",
                "via": "assumed",
                "at": sent,
            },
        ],
        {
            "current_mailman": "mailman-1",
            "events": [
                {
                    "event": "waiting",
                    "token_id": "mailman-1",
                    "at": NOW.isoformat(),
                }
            ],
        },
        {
            "slots": (AddressSlot("plan-b-builder", current_address="agent-b"),),
            "bindings": {"agent-b"},
            "live_addresses": {"agent-b"},
            "excluded_addresses": set(),
        },
        NOW,
    )

    assert report["relay"]["status"] == "up"
    assert report["unread_urgent"] == ["urgent-unread"]
    assert report["exit_code"] == 0


def test_doctor_works_with_real_empty_and_populated_store(tmp_path, capsys) -> None:
    args = SimpleNamespace(json=True)
    assert run(args, tmp_path) == 0
    empty = json.loads(capsys.readouterr().out)
    assert empty["recipients"] == []

    now = datetime.now(UTC)
    append_message(
        "sender",
        "main",
        "info",
        "old main mail",
        working=tmp_path,
        now=now - timedelta(minutes=30),
    )
    append_message(
        "sender",
        "ghost",
        "info",
        "unknown address",
        working=tmp_path,
        now=now - timedelta(minutes=5),
    )

    assert run(args, tmp_path) == 0
    populated = json.loads(capsys.readouterr().out)
    assert populated["overdue_by_cause"] == {"unresolvable": 1}
    assert populated["exit_code"] == 0


def test_doctor_reports_role_stream_without_a_live_holder() -> None:
    sent = (NOW - timedelta(minutes=12)).isoformat()
    report = aggregate_doctor(
        [{"id": "role-message", "to": "builder:plan-a", "kind": "info", "ts": sent}],
        [],
        {"events": []},
        {
            "slots": (AddressSlot("plan-a-builder"),),
            "bindings": set(),
            "live_addresses": set(),
            "excluded_addresses": set(),
        },
        NOW,
        role_inbox_active=True,
    )

    assert report["recipients"][0]["address"] == "builder:plan-a"
    assert report["overdue_by_cause"] == {"no-holder": 1}
