from datetime import UTC, datetime, timedelta

from varde_workflow.relay_state import (
    elapsed,
    end,
    heartbeat,
    lease_actions,
    load,
    mailman_alive,
    planning_state,
    record,
    recreate_due,
    renew,
    return_mailman,
)

TOKEN = "token"  # noqa: S105 - Fixture identifier for relay state tests.
FIRST_TOKEN = "first"  # noqa: S105 - Fixture identifier for relay state tests.
SECOND_TOKEN = "second"  # noqa: S105 - Fixture identifier for relay state tests.
SAME_TOKEN = "same-token"  # noqa: S105 - Fixture identifier for relay state tests.
MAILMAN_TOKEN = "mailman-token"  # noqa: S105 - Fixture identifier for relay state tests.


def test_mailman_liveness_uses_wait_heartbeat_and_return_grace(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    heartbeat(tmp_path, "token", "waiting", now)
    assert mailman_alive(tmp_path, "token", now + timedelta(seconds=89))
    assert not mailman_alive(tmp_path, "token", now + timedelta(seconds=90))
    heartbeat(tmp_path, "token", "returned", now)
    assert mailman_alive(tmp_path, "token", now + timedelta(minutes=4))
    assert not mailman_alive(tmp_path, "token", now + timedelta(minutes=5))
    heartbeat(tmp_path, "token", "ended", now)
    assert not mailman_alive(tmp_path, "token", now)


def test_lease_is_exclusive_until_expiry_and_expiry_is_not_an_attempt(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    action = {"address": "worker", "message_ids": ["m-12345678"]}
    first = lease_actions(tmp_path, [action], "token", now)[0]
    assert lease_actions(tmp_path, [action], "other", now) == []
    assert lease_actions(tmp_path, [action], "other", now + timedelta(minutes=5))
    assert first["expires_at"] == (now + timedelta(minutes=5)).isoformat().replace(
        "+00:00", "Z"
    )
    assert not any(
        event.get("event") in {"failed", "skipped-busy"}
        for event in __import__(
            "varde_workflow.inbox", fromlist=["delivery_events"]
        ).delivery_events(tmp_path)
    )


def test_planning_state_includes_active_lease_for_second_once(tmp_path) -> None:
    from varde_workflow.inbox import append_message
    from varde_workflow.relay_plan import plan

    now = datetime(2026, 1, 1, tzinfo=UTC)
    message = append_message(
        "main", "worker", "blocked", "one", working=tmp_path, now=now
    )
    lease_actions(
        tmp_path, [{"address": "worker", "message_ids": [message.id]}], "token", now
    )
    assert plan(planning_state(tmp_path), now)["actions"] == []


def test_slept_gap_is_removed_from_active_elapsed_time(tmp_path) -> None:
    from varde_workflow.relay_state import record

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=2)
    record(tmp_path, "slept", now=end, gap_seconds=3600)
    assert elapsed(tmp_path, start, end) == timedelta(hours=1)


def test_recreate_thresholds_use_delivery_window_and_context_growth(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    from varde_workflow.inbox import record_relay_event
    from varde_workflow.relay_state import heartbeat

    heartbeat(tmp_path, "mailman-token", "waiting", now)
    assert not recreate_due(tmp_path, now)
    for i in range(15):
        record_relay_event(
            tmp_path,
            f"m-{i:08x}",
            "worker",
            "pushed",
            now=now,
            token_id=MAILMAN_TOKEN,
        )
    assert recreate_due(tmp_path, now)
    age_root = tmp_path / "age"
    assert not recreate_due(age_root, now)
    heartbeat(age_root, "age-token", "waiting", now)
    assert recreate_due(age_root, now + timedelta(hours=24))
    context_root = tmp_path / "context"
    assert not recreate_due(
        context_root, now, context_tokens=50_000, baseline_tokens=10_001
    )
    assert not recreate_due(
        context_root, now, context_tokens=50_000, baseline_tokens=10_000
    )
    assert recreate_due(
        context_root, now, context_tokens=50_001, baseline_tokens=10_000
    )


def test_recreate_delivery_counter_uses_24_hour_window(tmp_path) -> None:
    from varde_workflow.inbox import record_relay_event

    now = datetime(2026, 1, 2, tzinfo=UTC)
    from varde_workflow.relay_state import heartbeat

    heartbeat(tmp_path, "token", "waiting", now - timedelta(hours=25))
    for index in range(15):
        at = now - timedelta(hours=25) if index == 0 else now - timedelta(hours=1)
        record_relay_event(
            tmp_path, f"m-{index:08x}", "reader", "pushed", now=at, token_id=TOKEN
        )
    assert recreate_due(tmp_path, now)


def test_recreate_counters_are_keyed_to_mailman_token(tmp_path) -> None:
    from varde_workflow.inbox import record_relay_event
    from varde_workflow.relay_state import heartbeat

    now = datetime(2026, 1, 2, tzinfo=UTC)
    heartbeat(tmp_path, "first", "waiting", now)
    heartbeat(tmp_path, "second", "waiting", now)
    for index in range(15):
        record_relay_event(
            tmp_path,
            f"m-{index:08x}",
            "worker",
            "pushed",
            now=now,
            token_id=FIRST_TOKEN,
        )
    assert recreate_due(tmp_path, now, token_id=FIRST_TOKEN)
    assert not recreate_due(tmp_path, now, token_id=SECOND_TOKEN)


def test_recreate_delivery_count_restarts_with_respawn(tmp_path) -> None:
    from varde_workflow.inbox import record_relay_event

    now = datetime(2026, 1, 2, tzinfo=UTC)
    heartbeat(tmp_path, "same-token", "waiting", now - timedelta(hours=1))
    for index in range(15):
        record_relay_event(
            tmp_path,
            f"m-{index:08x}",
            "worker",
            "pushed",
            now=now - timedelta(minutes=30),
            token_id=SAME_TOKEN,
        )
    assert recreate_due(tmp_path, now, token_id=SAME_TOKEN)

    end(tmp_path, SAME_TOKEN, now)
    heartbeat(tmp_path, SAME_TOKEN, "waiting", now + timedelta(minutes=1))
    assert not recreate_due(tmp_path, now + timedelta(minutes=1), token_id=SAME_TOKEN)
    for index in range(15, 30):
        record_relay_event(
            tmp_path,
            f"m-{index:08x}",
            "worker",
            "pushed",
            now=now + timedelta(minutes=2),
            token_id=SAME_TOKEN,
        )
    assert recreate_due(tmp_path, now + timedelta(minutes=2), token_id=SAME_TOKEN)


def test_recreate_delivery_count_resets_after_crash_without_ended_event(
    tmp_path, monkeypatch
) -> None:
    from varde_workflow.inbox import record_relay_event

    now = datetime(2026, 1, 2, tzinfo=UTC)
    monkeypatch.setattr("varde_workflow.relay_state.os.getpid", lambda: 100)
    heartbeat(tmp_path, "same-token", "waiting", now - timedelta(hours=25))
    for index in range(15):
        record_relay_event(
            tmp_path,
            f"m-{index:08x}",
            "worker",
            "pushed",
            now=now - timedelta(hours=1),
            token_id=SAME_TOKEN,
        )
    assert recreate_due(tmp_path, now, token_id=SAME_TOKEN)

    monkeypatch.setattr("varde_workflow.relay_state.os.getpid", lambda: 200)
    heartbeat(tmp_path, SAME_TOKEN, "waiting", now)
    assert not recreate_due(tmp_path, now, token_id=SAME_TOKEN)


def test_planning_state_stops_delivery_to_completed_plan(tmp_path) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message
    from varde_workflow.relay_plan import plan

    now = datetime(2026, 1, 1, tzinfo=UTC)
    plans = tmp_path / "plans" / "finished-plan"
    plans.mkdir(parents=True)
    (plans / "plan.md").write_text(
        "---\nid: finished-plan\nstatus: completed\n---\n", encoding="utf-8"
    )
    append_message(
        "main", "finished-plan", "blocked", "obsolete", working=tmp_path, now=now
    )
    store = BindingStore(tmp_path)
    marker = store.issue("finished-plan", now=now)
    assert store.redeem(marker, "finished-session", "claude", "/repo", now=now)
    state = planning_state(tmp_path, now=now)
    assert "finished-plan" in state["concluded_addresses"]
    assert any(event.get("event") == "target-gone" for event in state["events"])
    active = {
        **state,
        "concluded_addresses": [],
        "events": [
            event for event in state["events"] if event.get("event") != "target-gone"
        ],
    }
    due = now + timedelta(seconds=120)
    assert plan(active, due)["actions"]
    assert plan(state, due)["actions"] == []
    assert plan(state, due + timedelta(days=10))["actions"] == []


def test_concluded_address_record_survives_plan_removal(tmp_path) -> None:
    from varde_workflow.inbox import append_message
    from varde_workflow.relay_plan import plan
    from varde_workflow.relay_state import mark_address_concluded

    now = datetime(2026, 1, 1, tzinfo=UTC)
    append_message(
        "main", "removed-plan", "blocked", "obsolete", working=tmp_path, now=now
    )
    mark_address_concluded(tmp_path, "removed-plan")
    (tmp_path / "plans" / "removed-plan").mkdir(parents=True)
    state = planning_state(tmp_path, now=now)
    assert "removed-plan" in state["concluded_addresses"]
    assert plan(state, now + timedelta(seconds=120))["actions"] == []


def test_unbound_mail_remains_deliverable_after_long_gap(tmp_path) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message, delivery_events
    from varde_workflow.relay_plan import plan

    now = datetime(2026, 1, 2, tzinfo=UTC)
    sent = now - timedelta(days=30)
    message = append_message(
        "main", "orphan", "blocked", "old but deliverable", working=tmp_path, now=sent
    )
    store = BindingStore(tmp_path)
    marker = store.issue("orphan", now=now)
    assert store.redeem(marker, "orphan-session", "claude", "/repo", now=now)

    state = planning_state(tmp_path, now=now)
    assert not any(
        item.get("event") == "target-gone" and item.get("message_id") == message.id
        for item in delivery_events(tmp_path)
    )
    actions = plan(state, now)["actions"]
    assert any(
        action.get("address") == "orphan"
        and message.id in action.get("message_ids", [])
        for action in actions
    )


def test_sleep_extends_action_lease_without_counting_failure(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    lease_actions(
        tmp_path, [{"address": "worker", "message_ids": ["m-12345678"]}], "token", now
    )
    record(tmp_path, "slept", now=now + timedelta(minutes=30), gap_seconds=1800)
    state = load(tmp_path)
    assert state["leases"][0]["expires_at"] == (
        now + timedelta(minutes=35)
    ).isoformat().replace("+00:00", "Z")
    assert state.get("attempts", {}) == {}
    assert (
        lease_actions(
            tmp_path,
            [{"address": "worker", "message_ids": ["m-12345678"]}],
            "other",
            now + timedelta(minutes=30),
        )
        == []
    )


def test_sleep_gap_does_not_age_waiting_mailman_heartbeat(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    heartbeat(tmp_path, "token", "waiting", now)
    record(tmp_path, "slept", now=now + timedelta(minutes=30), gap_seconds=1800)
    assert mailman_alive(tmp_path, "token", now + timedelta(minutes=30))


def test_early_mailman_return_does_not_count_a_cycle(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert not return_mailman(tmp_path, "token", now, now + timedelta(minutes=1))
    assert load(tmp_path)["cycles"] == {}
    assert return_mailman(
        tmp_path, "token", now + timedelta(minutes=1), now + timedelta(minutes=1)
    )
    assert load(tmp_path)["cycles"]["token"] == 1


def test_cycles_count_ninety_percent_and_status_helpers_are_per_mailman(
    tmp_path,
) -> None:
    from varde_workflow.binding import BindingStore
    from varde_workflow.inbox import append_message
    from varde_workflow.relay_state import (
        action_record,
        heartbeat,
        mailman_block,
        superseded,
    )

    start = datetime(2026, 1, 1, tzinfo=UTC)
    deadline = start + timedelta(minutes=60)
    assert return_mailman(
        tmp_path, "t", start + timedelta(minutes=54), deadline, started=start
    )
    assert return_mailman(
        tmp_path,
        "t",
        start + timedelta(minutes=1),
        deadline,
        started=start,
        had_action=True,
    )
    assert load(tmp_path)["cycles"]["t"] == 1
    heartbeat(tmp_path, "t", "waiting", start, expect_return_by=deadline)
    message = append_message(
        "main", "worker", "blocked", "x", working=tmp_path, now=start
    )
    action = lease_actions(
        tmp_path, [{"address": "worker", "message_ids": [message.id]}], "t", start
    )[0]
    record = action_record(tmp_path, action["action_id"])
    assert record is not None
    assert record["message_ids"] == [message.id]
    assert mailman_block(tmp_path, "t", start)[
        "expect_return_by"
    ] == deadline.isoformat().replace("+00:00", "Z")
    store = BindingStore(tmp_path)
    marker = store.issue("mailman", now=start)
    assert store.redeem(marker, "s", "claude", "/repo", now=start)
    token_id = str(store.list_bindings()[0]["token_id"])
    assert not superseded(tmp_path, token_id)
    replacement = store.issue(
        "mailman", now=start + timedelta(minutes=1), supersede=True
    )
    assert store.redeem(
        replacement, "s2", "claude", "/repo", now=start + timedelta(minutes=1)
    )
    assert superseded(tmp_path, token_id)


def test_repeated_heartbeats_keep_latest_record_per_token(tmp_path) -> None:
    from varde_workflow.relay_state import heartbeat, load

    now = datetime(2026, 1, 1, tzinfo=UTC)
    for minute in range(100):
        heartbeat(tmp_path, "token", "waiting", now + timedelta(minutes=minute))
    events = [
        event for event in load(tmp_path)["events"] if event.get("token_id") == "token"
    ]
    assert len(events) == 1


def test_renew_extends_lease_and_end_marks_holder_dead(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    lease = lease_actions(
        tmp_path, [{"address": "worker", "message_ids": ["m-12345678"]}], "token", now
    )[0]
    assert renew(tmp_path, lease["action_id"], now + timedelta(minutes=1))
    assert load(tmp_path)["leases"][0]["expires_at"] == (
        now + timedelta(minutes=6)
    ).isoformat().replace("+00:00", "Z")
    heartbeat(tmp_path, "token", "waiting", now)
    end(tmp_path, "token", now + timedelta(seconds=1))
    assert not mailman_alive(tmp_path, "token", now + timedelta(seconds=1))


def test_superseded_mailman_end_keeps_new_mailman_current(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    heartbeat(tmp_path, "old", "waiting", now)
    heartbeat(tmp_path, "new", "waiting", now)
    end(tmp_path, "old", now + timedelta(seconds=1))
    assert load(tmp_path)["current_mailman"] == "new"
