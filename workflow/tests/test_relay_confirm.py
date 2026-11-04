from datetime import UTC, datetime, timedelta

from varde_workflow.inbox import append_message, delivery_events, record_relay_event
from varde_workflow.relay_plan import next_due, plan
from varde_workflow.relay_state import confirm, lease_actions

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _leased(tmp_path, *, harness="claude", ids=1):
    messages = [
        append_message(
            "main", "worker", "blocked", f"urgent {i}", working=tmp_path, now=NOW
        )
        for i in range(ids)
    ]
    return messages, lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [m.id for m in messages]}],
        "token",
        NOW,
        harness=harness,
    )[0]


def test_push_receipt_is_first_delivery_and_duplicate_confirm_is_noop(tmp_path) -> None:
    messages, action = _leased(tmp_path)
    assert messages[0].id is not None
    result = confirm(
        tmp_path, action["action_id"], "pushed", NOW + timedelta(seconds=1)
    )
    assert result["status"] == "confirmed"
    assert (
        confirm(tmp_path, action["action_id"], "pushed", NOW + timedelta(seconds=2))[
            "status"
        ]
        == "duplicate"
    )
    assert record_relay_event(
        tmp_path,
        messages[0].id,
        "worker",
        "delivered",
        now=NOW + timedelta(seconds=3),
        via="receipt",
    )
    assert not record_relay_event(
        tmp_path,
        messages[0].id,
        "worker",
        "delivered",
        now=NOW + timedelta(seconds=4),
        via="hook",
    )
    assert (
        plan(
            {"messages": [messages[0].to_dict()], "events": delivery_events(tmp_path)},
            NOW + timedelta(hours=1),
        )["actions"]
        == []
    )
    assert [
        event["via"]
        for event in delivery_events(tmp_path)
        if event["event"] == "delivered"
    ] == ["receipt"]


def test_non_receipt_harness_records_assumed_delivery_without_suspect(tmp_path) -> None:
    _message, action = _leased(tmp_path, harness="opencode")
    confirm(tmp_path, action["action_id"], "pushed", NOW)
    events = delivery_events(tmp_path)
    assert any(e["event"] == "delivered" and e["via"] == "assumed" for e in events)
    assert not any(e["event"] == "suspect" for e in events)


def test_target_gone_confirmation_stops_future_retries(tmp_path) -> None:
    messages, action = _leased(tmp_path)
    confirm(tmp_path, action["action_id"], "target-gone", NOW)

    result = plan(
        {
            "messages": [messages[0].to_dict()],
            "events": delivery_events(tmp_path),
            "bindings": [
                {
                    "address": "worker",
                    "harness": "paseo",
                    "last_seen": (NOW - timedelta(hours=1)).isoformat(),
                }
            ],
        },
        NOW + timedelta(days=1),
    )

    assert result["actions"] == []


def test_busy_and_failed_attempts_back_off_then_escalate(tmp_path) -> None:
    msg, action = _leased(tmp_path)
    for attempt, minute in enumerate((0, 2, 9)):
        at = NOW + timedelta(minutes=minute)
        confirm(tmp_path, action["action_id"], "skipped-busy", at)
        if attempt < 2:
            action = lease_actions(
                tmp_path,
                [{"address": "worker", "message_ids": [msg[0].id]}],
                "token",
                at + timedelta(minutes=(1, 5)[attempt]),
            )[0]
    events = delivery_events(tmp_path)
    assert sum(e["event"] == "skipped-busy" for e in events) == 3
    assert next_due(
        {
            "messages": [
                {
                    "id": msg[0].id,
                    "to": "worker",
                    "kind": "blocked",
                    "ts": NOW.isoformat(),
                }
            ],
            "events": events,
            "bindings": [
                {
                    "address": "worker",
                    "harness": "claude",
                    "last_seen": (NOW - timedelta(hours=1)).isoformat(),
                }
            ],
        },
        NOW + timedelta(minutes=10),
    ) == NOW + timedelta(minutes=10)


def test_next_due_tracks_regular_active_receipt_and_lease_timers() -> None:
    message = {
        "id": "m-12345678",
        "to": "worker",
        "kind": "info",
        "ts": NOW.isoformat(),
    }
    state = {
        "messages": [message],
        "bindings": [
            {"address": "worker", "harness": "claude", "last_seen": NOW.isoformat()}
        ],
        "events": [
            {
                "event": "pushed",
                "message_id": message["id"],
                "harness": "claude",
                "at": NOW.isoformat(),
            }
        ],
        "leases": [{"expires_at": (NOW + timedelta(minutes=5)).isoformat()}],
    }
    assert next_due(state, NOW) == NOW + timedelta(seconds=120)
    assert next_due({"messages": [message]}, NOW) == NOW + timedelta(minutes=2)
    urgent = {**message, "kind": "blocked"}
    assert next_due(
        {"messages": [urgent], "events": state["events"]}, NOW
    ) == NOW + timedelta(minutes=2)
    aged = {
        "messages": [urgent],
        "events": state["events"],
        "bindings": [
            {"address": "worker", "last_seen": (NOW - timedelta(minutes=3)).isoformat()}
        ],
    }
    assert next_due(aged, NOW, {"receipt_minutes": 3}) == NOW + timedelta(minutes=3)
    assert next_due({"leases": state["leases"]}, NOW) == NOW + timedelta(minutes=5)


def test_sleep_gap_shifts_planner_timers() -> None:
    woke = NOW + timedelta(minutes=30)
    message = {
        "id": "m-12345678",
        "to": "worker",
        "kind": "info",
        "ts": NOW.isoformat(),
    }
    state = {
        "messages": [message],
        "bindings": [
            {
                "address": "worker",
                "harness": "claude",
                "last_seen": (NOW - timedelta(hours=1)).isoformat(),
            }
        ],
        "events": [{"event": "slept", "at": woke.isoformat(), "gap_seconds": 1800}],
    }
    assert plan(state, woke)["actions"] == []
    assert next_due(state, woke) == woke


def test_actions_are_one_per_reader_and_regular_digest_is_capped_at_twenty(
    tmp_path,
) -> None:
    from varde_workflow.inbox import append_message
    from varde_workflow.relay_plan import plan

    old = NOW - timedelta(minutes=3)
    msgs = [
        append_message("main", "worker", "info", str(i), working=tmp_path, now=old)
        for i in range(21)
    ]
    actions = plan(
        {
            "messages": [m.to_dict() for m in msgs],
            "bindings": [
                {
                    "address": "worker",
                    "harness": "claude",
                    "last_seen": (NOW - timedelta(hours=1)).isoformat(),
                }
            ],
        },
        NOW,
    )["actions"]
    assert len(actions) == 1
    assert actions[0]["message_ids"] == [m.id for m in msgs[:20]]


def test_relay_plan_backoff_sequences_and_fourth_failure_is_not_planned() -> None:
    from varde_workflow.relay_plan import _backoff

    message = {
        "id": "m-12345678",
        "to": "worker",
        "kind": "blocked",
        "ts": NOW.isoformat(),
    }
    for result, delays in (("skipped-busy", (1, 2, 5, 5)), ("failed", (1, 5, 15))):
        events = []
        at = NOW
        for delay in delays:
            events.append(
                {"event": result, "message_id": message["id"], "at": at.isoformat()}
            )
            assert _backoff(events, message["id"])[1] == at + timedelta(minutes=delay)
            state = {
                "messages": [message],
                "events": events,
                "bindings": [
                    {
                        "address": "worker",
                        "harness": "claude",
                        "last_seen": (NOW - timedelta(minutes=3)).isoformat(),
                    }
                ],
            }
            if result == "skipped-busy" or len(events) < 3:
                due = at + timedelta(minutes=delay)
                assert next_due(state, at) == min(due, NOW + timedelta(minutes=10))
            at += timedelta(minutes=delay)
        if result == "failed":
            events.append(
                {"event": "failed", "message_id": message["id"], "at": at.isoformat()}
            )
            assert plan({"messages": [message], "events": events}, at)["actions"] == []


def test_three_failed_attempts_escalate_once_and_main_escalations_are_terminal(
    tmp_path,
) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.relay_state import escalate_due

    bindings = BindingStore(tmp_path)
    marker = bindings.issue("worker", now=NOW)
    assert bindings.redeem(marker, "worker-session", "claude", "/repo", now=NOW)
    messages, action = _leased(tmp_path)
    for attempt, minute in enumerate((0, 2, 8), start=1):
        at = NOW + timedelta(minutes=minute)
        confirm(tmp_path, action["action_id"], "failed", at)
        if attempt < 3:
            action = lease_actions(
                tmp_path,
                [{"address": "worker", "message_ids": [messages[0].id]}],
                "token",
                at + timedelta(minutes=(1, 5)[attempt - 1]),
            )[0]
    assert escalate_due(tmp_path, NOW + timedelta(minutes=9)) == []
    assert escalate_due(tmp_path, NOW + timedelta(minutes=10)) == [messages[0].id]
    assert escalate_due(tmp_path, NOW + timedelta(minutes=11)) == []
    state = {
        "messages": [
            m.to_dict()
            for m in __import__("varde_workflow.inbox", fromlist=["read_all"]).read_all(
                tmp_path
            )
        ],
        "events": delivery_events(tmp_path),
    }
    assert all(
        action["address"] != "main"
        for action in plan(state, NOW + timedelta(hours=1))["actions"]
    )


def test_expired_receipt_capable_push_becomes_suspect_but_assumed_stays_delivered(
    tmp_path,
) -> None:
    from varde_workflow.relay_state import suspect_due

    capable, capable_action = _leased(tmp_path)
    confirm(tmp_path, capable_action["action_id"], "pushed", NOW)
    assert suspect_due(tmp_path, NOW + timedelta(minutes=9)) == []
    assert suspect_due(tmp_path, NOW + timedelta(minutes=10)) == [capable[0].id]
    assert suspect_due(tmp_path, NOW + timedelta(minutes=11)) == []

    other = tmp_path / "other"
    _assumed, assumed_action = _leased(other, harness="opencode")
    confirm(other, assumed_action["action_id"], "pushed", NOW)
    assert suspect_due(other, NOW + timedelta(hours=1)) == []


def test_push_waits_for_receipt_window_then_suspect_can_be_replanned(tmp_path) -> None:
    from varde_workflow.relay_state import suspect_due

    messages, action = _leased(tmp_path)
    confirm(tmp_path, action["action_id"], "pushed", NOW)
    from varde_workflow.binding import BindingStore

    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "s", "claude", "/repo", now=NOW)
    state = {
        "messages": [messages[0].to_dict()],
        "events": delivery_events(tmp_path),
        "bindings": store.list_bindings(),
    }
    assert plan(state, NOW + timedelta(minutes=9))["actions"] == []
    assert suspect_due(tmp_path, NOW + timedelta(minutes=10)) == [messages[0].id]
    state["events"] = delivery_events(tmp_path)
    assert plan(state, NOW + timedelta(minutes=11))["actions"]


def test_late_assumed_confirm_removes_message_from_newer_action(tmp_path) -> None:
    from varde_workflow.relay_state import load

    first = append_message("main", "worker", "info", "first", working=tmp_path, now=NOW)
    second = append_message(
        "main", "worker", "info", "second", working=tmp_path, now=NOW
    )
    old = lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [first.id]}],
        "token",
        NOW,
        harness="opencode",
    )[0]
    newer = lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [first.id, second.id]}],
        "token",
        NOW + timedelta(minutes=5),
        harness="opencode",
    )[0]
    confirm(tmp_path, old["action_id"], "pushed", NOW + timedelta(minutes=6))
    state = load(tmp_path)
    updated = next(
        item for item in state["leases"] if item["action_id"] == newer["action_id"]
    )
    assert updated["message_ids"] == [second.id]


def test_two_target_gone_results_mark_wake_gone(tmp_path) -> None:
    from varde_workflow.binding import BindingStore

    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "s", "claude", "/repo", now=NOW)
    for minute in (0, 2):
        action = lease_actions(
            tmp_path,
            [{"address": "worker", "message_ids": [f"m-{minute:08x}"]}],
            "token",
            NOW + timedelta(minutes=minute),
        )[0]
        confirm(
            tmp_path,
            action["action_id"],
            "target-gone",
            NOW + timedelta(minutes=minute),
        )
    assert store.list_bindings()[0]["wake"] == "gone"


def test_escalation_thresholds_cover_unbound_busy_regular_and_main(
    tmp_path,
) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import record_relay_event
    from varde_workflow.relay_state import escalate_due

    urgent = append_message(
        "sender", "unbound", "blocked", "urgent", working=tmp_path, now=NOW
    )
    regular = append_message(
        "sender", "regular", "info", "digest", working=tmp_path, now=NOW
    )
    main_bound = append_message(
        "relay", "main", "blocked", "already escalated", working=tmp_path, now=NOW
    )
    assert escalate_due(tmp_path, NOW + timedelta(minutes=1)) == []
    assert escalate_due(tmp_path, NOW + timedelta(minutes=2)) == [
        urgent.id,
        regular.id,
    ]
    assert any(
        e.get("source_id") == regular.id and e["event"] == "escalated"
        for e in delivery_events(tmp_path)
    )
    assert main_bound.id not in {e.get("source_id") for e in delivery_events(tmp_path)}

    busy_root = tmp_path / "busy"
    holder = BindingStore(busy_root)
    marker = holder.issue("busy-worker", now=NOW)
    assert holder.redeem(marker, "session", "claude", "/repo", now=NOW)
    busy_message = append_message(
        "sender", "busy-worker", "blocked", "urgent", working=busy_root, now=NOW
    )
    assert busy_message.id is not None
    record_relay_event(
        busy_root, busy_message.id, "busy-worker", "skipped-busy", now=NOW
    )
    assert escalate_due(busy_root, NOW + timedelta(minutes=9)) == []
    assert escalate_due(busy_root, NOW + timedelta(minutes=10)) == [busy_message.id]


def test_delivered_and_acked_unbound_urgent_is_not_escalated(tmp_path) -> None:
    from varde_workflow.relay_state import escalate_due

    message = append_message(
        "sender", "former-worker", "blocked", "done", working=tmp_path, now=NOW
    )
    assert message.id is not None
    record_relay_event(
        tmp_path, message.id, message.to, "delivered", now=NOW, via="hook"
    )
    record_relay_event(tmp_path, message.id, message.to, "acked", now=NOW, via="cli")
    assert escalate_due(tmp_path, NOW + timedelta(hours=2)) == []


def test_escalation_append_is_recovered_by_source_message_id(tmp_path) -> None:
    from varde_workflow.inbox import read_all
    from varde_workflow.relay_state import escalate_due

    message = append_message(
        "sender", "missing", "blocked", "urgent", working=tmp_path, now=NOW
    )
    append_message(
        "relay",
        "main",
        "blocked",
        f"Message {message.id} to missing remains undelivered",
        working=tmp_path,
        now=NOW + timedelta(minutes=10),
    )
    assert escalate_due(tmp_path, NOW + timedelta(minutes=10)) == []
    assert sum(item.from_ == "relay" for item in read_all(tmp_path)) == 1


def test_per_message_result_first_wins_and_late_pushed_shrinks_receipt_action(
    tmp_path,
) -> None:
    from varde_workflow.relay_state import load

    first = append_message(
        "main", "worker", "blocked", "first", working=tmp_path, now=NOW
    )
    second = append_message(
        "main", "worker", "blocked", "second", working=tmp_path, now=NOW
    )
    older = lease_actions(
        tmp_path, [{"address": "worker", "message_ids": [first.id]}], "old", NOW
    )[0]
    newer = lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [first.id, second.id]}],
        "new",
        NOW + timedelta(minutes=5),
    )[0]
    result = confirm(tmp_path, older["action_id"], "pushed", NOW + timedelta(minutes=6))
    assert result["message_ids"] == [first.id]
    leases = load(tmp_path)["leases"]
    assert next(item for item in leases if item["action_id"] == newer["action_id"])[
        "message_ids"
    ] == [second.id]
    second_old = lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [second.id]}],
        "old",
        NOW + timedelta(minutes=10),
    )[0]
    second_new = lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [second.id]}],
        "new",
        NOW + timedelta(minutes=15),
    )[0]
    confirm(tmp_path, second_new["action_id"], "pushed", NOW + timedelta(minutes=16))
    confirm(tmp_path, second_old["action_id"], "failed", NOW + timedelta(minutes=17))
    assert not any(
        event.get("message_id") == second.id and event["event"] == "failed"
        for event in delivery_events(tmp_path)
    )


def test_three_suspects_count_toward_escalation_cap(tmp_path) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.relay_state import escalate_due, suspect_due

    message = append_message(
        "main", "worker", "blocked", "suspect", working=tmp_path, now=NOW
    )
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "s", "claude", "/repo", now=NOW)
    action = lease_actions(
        tmp_path,
        [{"address": "worker", "message_ids": [message.id]}],
        "token",
        NOW,
        harness="claude",
    )[0]
    for index in range(3):
        at = NOW + timedelta(minutes=index * 11)
        if index:
            action = lease_actions(
                tmp_path,
                [{"address": "worker", "message_ids": [message.id]}],
                "token",
                at,
                harness="claude",
            )[0]
        confirm(tmp_path, action["action_id"], "pushed", at)
        assert suspect_due(tmp_path, at + timedelta(minutes=10)) == [message.id]
    assert escalate_due(tmp_path, NOW + timedelta(minutes=35)) == [message.id]


def test_confirm_resumes_confirming_action_and_logs_unknown_ids(tmp_path) -> None:
    import json

    from varde_workflow.relay_state import action_record

    _messages, action = _leased(tmp_path)
    path = (
        tmp_path
        / ".cache"
        / "inbox"
        / "relay"
        / "actions"
        / f"{action['action_id']}.json"
    )
    record = action_record(tmp_path, action["action_id"])
    assert record is not None
    record.update(status="confirming", result="failed")
    path.write_text(json.dumps(record))
    assert confirm(tmp_path, action["action_id"], "pushed", NOW)["result"] == "failed"
    assert any(event["event"] == "failed" for event in delivery_events(tmp_path))
    assert confirm(tmp_path, "missing-action", "failed", NOW)["status"] == "unknown"
    assert any(
        event["event"] == "unknown-confirm"
        for event in __import__("varde_workflow.relay_state", fromlist=["load"]).load(
            tmp_path
        )["events"]
    )


def test_lease_uses_each_recipient_wake_harness(tmp_path) -> None:
    messages = [
        append_message("main", address, "blocked", address, working=tmp_path, now=NOW)
        for address in ("claude-worker", "opencode-worker")
    ]
    leases = lease_actions(
        tmp_path,
        [
            {
                "address": "claude-worker",
                "message_ids": [messages[0].id],
                "wake": {"harness": "claude"},
            },
            {
                "address": "opencode-worker",
                "message_ids": [messages[1].id],
                "wake": {"harness": "opencode"},
            },
        ],
        "mailman",
        NOW,
    )
    assert [item["harness"] for item in leases] == ["claude", "opencode"]
