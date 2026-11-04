from __future__ import annotations

from datetime import UTC, datetime

from varde_workflow.soak import evaluate

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def records(**overrides):
    data = {
        "messages": [],
        "deliveries": [],
        "relay_events": [],
        "live_addresses": {"orchestrator-1"},
        "nudges": [],
        "status": {"exit_code": 0},
        "approved_merges": [],
        "open_requests": [],
        "active_orchestrators_today": 1,
        "prior_days": [],
    }
    data.update(overrides)
    return data


def criterion(report, identifier):
    return next(item for item in report["criteria"] if item["id"] == identifier)


def test_latency_p95_uses_earliest_event_per_bound_message_and_skips_main() -> None:
    messages = [
        {"id": f"m{i}", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"}
        for i in range(5)
    ] + [{"id": "main", "to": "main", "ts": "2026-10-23T10:00:00Z"}]
    deliveries = []
    for i in range(5):
        deliveries.extend(
            [
                {
                    "message_id": f"m{i}",
                    "reader": "orchestrator-1",
                    "event": "delivered",
                    "at": f"2026-10-23T10:0{i + 1}:00Z",
                },
                {
                    "message_id": f"m{i}",
                    "reader": "orchestrator-1",
                    "event": "delivered",
                    "at": "2026-10-23T10:30:00Z",
                },
                {
                    "message_id": f"m{i}",
                    "reader": "orchestrator-1",
                    "event": "acked",
                    "at": f"2026-10-23T10:0{i + 2}:00Z",
                },
            ]
        )
    deliveries.extend(
        [
            {
                "message_id": "main",
                "reader": "main",
                "event": "delivered",
                "at": "2026-10-23T10:00:01Z",
            },
            {
                "message_id": "main",
                "reader": "main",
                "event": "acked",
                "at": "2026-10-23T10:00:01Z",
            },
        ]
    )

    report = evaluate(records(messages=messages, deliveries=deliveries), 1, NOW, {})

    delivered = criterion(report, "delivered-latency")
    acked = criterion(report, "ack-latency")
    assert delivered["n"] == 5
    assert delivered["value"] == 300.0
    assert delivered["ok"] is False
    assert delivered["insufficient"] is False
    assert acked["n"] == 5
    assert acked["value"] == 360.0


def test_latency_criteria_are_insufficient_below_five_observations() -> None:
    report = evaluate(records(), 7, NOW, {})

    for name in ("delivered-latency", "ack-latency"):
        assert criterion(report, name) == {
            "id": name,
            "value": None,
            "threshold": 120 if name == "delivered-latency" else 1800,
            "ok": True,
            "n": 0,
            "insufficient": True,
        }


def test_gate_metrics_count_delivered_wakes_missed_and_unique_recipients():
    messages = [
        {"id": "wake-a", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"},
        {"id": "wake-b", "to": "planner-1", "ts": "2026-10-23T10:00:00Z"},
        {"id": "missed", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"},
        {"id": "recent", "to": "planner-1", "ts": "2026-10-23T11:59:30Z"},
        {"id": "main", "to": "main", "ts": "2026-10-23T10:00:00Z"},
        {"id": "retired", "to": "retired", "ts": "2026-10-23T10:00:00Z"},
    ]
    deliveries = [
        {
            "message_id": "wake-a",
            "reader": "orchestrator-1",
            "event": "delivered",
            "at": "2026-10-23T10:00:30Z",
        },
        {
            "message_id": "wake-a",
            "reader": "orchestrator-1",
            "event": "delivered",
            "at": "2026-10-23T10:30:00Z",
        },
        {
            "message_id": "wake-b",
            "reader": "planner-1",
            "event": "delivered",
            "at": "2026-10-23T10:01:10Z",
        },
    ]

    report = evaluate(
        records(
            messages=messages,
            deliveries=deliveries,
            live_addresses={"orchestrator-1", "planner-1"},
        ),
        1,
        NOW,
        {"delivered-latency": 60, "minimum_messages": 20},
    )
    default_report = evaluate(
        records(
            messages=messages,
            deliveries=deliveries,
            live_addresses={"orchestrator-1", "planner-1"},
        ),
        1,
        NOW,
        {},
    )

    assert report["wakes"] == 2
    assert report["missed"] == 1
    assert report["distinct_recipients"] == 2
    assert report["max_delivered_latency_s"] == 70.0
    assert report["all_ok"] is True
    assert default_report["all_ok"] is True


def test_live_binding_scopes_latency_status_and_undeliverable_count() -> None:
    messages = [
        {"id": "live", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"},
        {"id": "dead", "to": "old-slot", "ts": "2026-10-23T10:00:00Z"},
    ]
    deliveries = [
        {
            "message_id": message["id"],
            "reader": message["to"],
            "event": "delivered",
            "at": "2026-10-23T10:10:00Z",
        }
        for message in messages
    ]
    report = evaluate(
        records(
            messages=messages,
            deliveries=deliveries,
            live_addresses={"orchestrator-1"},
            status={"exit_code": 1},
        ),
        1,
        NOW,
        {},
    )

    assert criterion(report, "delivered-latency")["n"] == 1
    assert criterion(report, "status-clean")["ok"] is False
    assert report["undeliverable"] == 1

    unlive_only = evaluate(
        records(
            messages=[messages[1]],
            live_addresses={"orchestrator-1"},
            status={"exit_code": 1},
        ),
        1,
        NOW,
        {},
    )
    assert criterion(unlive_only, "status-clean")["ok"] is False


def test_send_no_mailman_uses_window_rate_and_insufficient_floor() -> None:
    events = [
        {"event": "send-liveness", "at": "2026-10-23T10:00:00Z", "alive": False}
    ] + [
        {"event": "send-liveness", "at": "2026-10-23T10:01:00Z", "alive": True}
        for _ in range(4)
    ]
    report = evaluate(records(relay_events=events), 1, NOW, {})
    assert criterion(report, "send-no-mailman") == {
        "id": "send-no-mailman",
        "value": 0.2,
        "threshold": 0.02,
        "ok": False,
        "n": 5,
        "insufficient": False,
    }
    short = evaluate(records(relay_events=events[:4]), 1, NOW, {})
    assert criterion(short, "send-no-mailman")["insufficient"] is True


def test_main_nudge_in_prior_evening_counts_at_0315_evaluation() -> None:
    data = records(
        nudges=[
            {"event": "main-nudge", "at": "2026-10-22T20:00:00Z"},
            {"event": "main-nudge", "at": "2026-10-23T03:16:00Z"},
        ]
    )

    evaluation_time = datetime(2026, 10, 23, 3, 15, tzinfo=UTC)
    report = evaluate(data, 1, evaluation_time, {})

    assert criterion(report, "main-nudges")["value"] == 1
    assert criterion(report, "main-nudges")["ok"] is False
    data["nudges"].pop(0)
    assert (
        criterion(evaluate(data, 1, evaluation_time, {}), "main-nudges")["ok"] is True
    )


def test_main_nudge_look_back_is_24_hours_for_multi_day_window() -> None:
    old = {"event": "main-nudge", "at": "2026-10-22T06:00:00Z"}
    recent = {"event": "main-nudge", "at": "2026-10-22T16:00:00Z"}

    report = evaluate(records(nudges=[old]), 3, NOW, {})
    assert criterion(report, "main-nudges")["ok"] is True
    report = evaluate(records(nudges=[recent]), 3, NOW, {})
    assert criterion(report, "main-nudges")["ok"] is False


def test_status_clean_fails_when_status_exit_is_nonzero() -> None:
    report = evaluate(
        records(
            status={"exit_code": 1},
            messages=[
                {"id": "m", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"}
            ],
        ),
        1,
        NOW,
        {},
    )
    assert criterion(report, "status-clean")["value"] == 1
    assert criterion(report, "status-clean")["ok"] is False


def test_merge_guard_fails_for_stale_approval_and_open_request() -> None:
    report = evaluate(
        records(
            approved_merges=[
                {"plan": "old", "approved_at": "2026-10-23T11:00:00Z", "merged": False}
            ],
            open_requests=[{"id": "request", "kind": "blocked"}],
        ),
        1,
        NOW,
        {},
    )
    assert criterion(report, "merge-guard")["value"] == 1
    assert criterion(report, "merge-guard")["ok"] is False


def test_corrupt_approved_at_fails_merge_guard_visibly() -> None:
    report = evaluate(
        records(
            approved_merges=[{"plan": "corrupt", "approved_at": "bad", "merged": False}]
        ),
        1,
        NOW,
        {},
    )
    merge_guard = criterion(report, "merge-guard")
    assert merge_guard["value"] == 1
    assert merge_guard["ok"] is False


def test_replay_requires_ack_then_sleep_then_redelivery() -> None:
    message = {"id": "m", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"}
    deliveries = [
        {
            "message_id": "m",
            "reader": "orchestrator-1",
            "event": "delivered",
            "at": "2026-10-23T10:01:00Z",
        },
        {
            "message_id": "m",
            "reader": "orchestrator-1",
            "event": "acked",
            "at": "2026-10-23T10:02:00Z",
        },
        {
            "message_id": "m",
            "reader": "orchestrator-1",
            "event": "delivered",
            "at": "2026-10-23T10:04:00Z",
        },
    ]

    without_sleep = evaluate(
        records(messages=[message], deliveries=deliveries), 1, NOW, {}
    )
    slept_before_ack = evaluate(
        records(
            messages=[message],
            deliveries=deliveries,
            relay_events=[
                deliveries[0],
                {"event": "slept", "at": "2026-10-23T10:01:30Z"},
                deliveries[1],
                deliveries[2],
            ],
        ),
        1,
        NOW,
        {},
    )
    slept_after_ack = evaluate(
        records(
            messages=[message],
            deliveries=deliveries,
            relay_events=[
                *deliveries[:2],
                {"event": "slept", "at": "2026-10-23T10:03:00Z"},
                deliveries[2],
            ],
        ),
        1,
        NOW,
        {},
    )

    assert criterion(without_sleep, "replays")["value"] == 0
    assert criterion(slept_before_ack, "replays")["value"] == 0
    assert criterion(slept_after_ack, "replays")["value"] == 1


def test_replay_tied_timestamps_follow_log_list_order() -> None:
    message = {"id": "m", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"}
    ack = {
        "message_id": "m",
        "reader": "orchestrator-1",
        "event": "acked",
        "at": "2026-10-23T10:02:00Z",
    }
    delivered = {
        "message_id": "m",
        "reader": "orchestrator-1",
        "event": "delivered",
        "at": "2026-10-23T10:02:00Z",
    }
    sleep = {"event": "slept", "at": "2026-10-23T10:02:00Z"}
    ordered = evaluate(
        records(
            messages=[message],
            deliveries=[ack, delivered],
            relay_events=[ack, sleep, delivered],
        ),
        1,
        NOW,
        {},
    )
    reversed_log = evaluate(
        records(
            messages=[message],
            deliveries=[delivered, ack],
            relay_events=[delivered, ack, sleep],
        ),
        1,
        NOW,
        {},
    )
    assert criterion(ordered, "replays")["value"] == 1
    assert criterion(reversed_log, "replays")["value"] == 0


def test_bad_delivery_time_is_skipped() -> None:
    report = evaluate(
        records(
            messages=[
                {"id": "m", "to": "orchestrator-1", "ts": "2026-10-23T10:00:00Z"}
            ],
            deliveries=[
                {
                    "message_id": "m",
                    "reader": "orchestrator-1",
                    "event": "delivered",
                    "at": "bad",
                }
            ],
        ),
        1,
        NOW,
        {},
    )
    assert criterion(report, "delivered-latency")["n"] == 0
    assert criterion(report, "replays")["value"] == 0


def test_window_excludes_old_message_and_main_from_latency() -> None:
    report = evaluate(
        records(
            messages=[
                {"id": "old", "to": "orchestrator-1", "ts": "2026-10-20T10:00:00Z"},
                {"id": "main", "to": "main", "ts": "2026-10-23T10:00:00Z"},
            ],
            deliveries=[
                {
                    "message_id": "old",
                    "reader": "orchestrator-1",
                    "event": "delivered",
                    "at": "2026-10-20T10:00:01Z",
                },
                {
                    "message_id": "main",
                    "reader": "main",
                    "event": "delivered",
                    "at": "2026-10-23T10:00:01Z",
                },
            ],
        ),
        1,
        NOW,
        {},
    )
    assert criterion(report, "delivered-latency")["n"] == 0


def test_zero_active_orchestrators_prevents_passing_day() -> None:
    report = evaluate(records(active_orchestrators_today=0), 1, NOW, {})
    assert report["all_ok"] is False
    assert report["days_ok_streak"] == 0


def test_streak_requires_calendar_days_and_ignores_today_and_input_order() -> None:
    data = records(
        prior_days=[
            {"date": "2026-10-23", "all_ok": False},
            {"date": "2026-10-22", "all_ok": True},
            {"date": "2026-10-20", "all_ok": True},
            {"date": "2026-10-21", "all_ok": True},
        ]
    )
    assert evaluate(data, 1, NOW, {})["days_ok_streak"] == 4
    data["prior_days"].append({"date": "2026-10-19", "all_ok": True})
    assert evaluate(data, 1, NOW, {})["days_ok_streak"] == 5
    data["prior_days"].append({"date": "2026-10-21", "all_ok": False})
    assert evaluate(data, 1, NOW, {})["days_ok_streak"] == 2
