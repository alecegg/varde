from datetime import UTC, datetime, timedelta

import pytest
from varde_data.views.message_receipts import undelivered_deadlines
from varde_data.views.relay_plan import classify_failure, plan


def test_plan_resolves_each_distinct_address_once():
    calls = []

    def resolve(address: str) -> str:
        calls.append(address)
        return address

    state = {
        "messages": [
            {"id": f"m-{index}", "to": "reader", "from": "sender"}
            for index in range(40)
        ],
        "bindings": [{"address": "reader"}],
        "events": [{"reader": "reader"} for _ in range(100)],
    }

    plan(state, datetime(2026, 10, 26, tzinfo=UTC), resolve_reader=resolve)

    assert calls == ["reader", "sender"]


@pytest.mark.parametrize(
    ("events", "recipient", "bindings", "known", "expected"),
    (
        (
            [{"event": "target-gone", "message_id": "m-1", "reader": "ghost"}],
            "ghost",
            set(),
            set(),
            "unresolvable",
        ),
        ([], "plan-a-builder", set(), {"plan-a-builder"}, "no-holder"),
        (
            [
                {
                    "event": "skipped-busy",
                    "message_id": "m-1",
                    "reader": "reader",
                    "reason": "active turn",
                }
            ],
            "reader",
            {"reader"},
            {"reader"},
            "busy (active turn)",
        ),
        ([], "worker", set(), {"worker"}, "unbound"),
        (
            [
                {
                    "event": "failed",
                    "message_id": "m-1",
                    "reader": "reader",
                    "reason": "provider timeout",
                }
            ],
            "reader",
            {"reader"},
            {"reader"},
            "no-receipt (provider timeout)",
        ),
    ),
)
def test_escalation_cause_classification(events, recipient, bindings, known, expected):
    assert classify_failure(events, "m-1", recipient, bindings, known) == expected


def test_escalation_resolves_slot_address_before_deadline():
    from varde_data.views.relay_plan import resolve_slot_addresses

    state = {
        "messages": [{"id": "m-1", "to": "old-worker", "from": "sender"}],
        "bindings": [{"address": "worker"}],
        "events": [],
    }
    resolved = resolve_slot_addresses(
        state, lambda address: {"old-worker": "worker"}.get(address, address)
    )
    assert resolved["messages"][0]["to"] == "worker"
    assert resolved["bindings"][0]["address"] == "worker"


def test_orchestrator_number_is_classified_as_a_role_address():
    assert (
        classify_failure([], "m-1", "orchestrator-2", set(), {"orchestrator-2"})
        == "no-holder"
    )


def test_unbound_recipient_escalates_after_two_minutes():
    sent = datetime(2026, 10, 26, tzinfo=UTC)
    deadline = undelivered_deadlines(
        [{"id": "m-1", "to": "orchestrator:plan", "ts": sent.isoformat()}],
        [],
        sent + timedelta(minutes=1),
        unbound_addresses={"orchestrator:plan"},
    )
    assert deadline["m-1"] == sent + timedelta(minutes=2)
