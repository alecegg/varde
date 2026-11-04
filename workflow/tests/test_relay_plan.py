from datetime import UTC, datetime, timedelta

from varde_workflow.relay_plan import next_due, plan


def test_urgent_actions_precede_regular_messages_and_respect_caps() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    messages = [
        {
            "id": f"m-{i:08x}",
            "to": f"worker{i}",
            "kind": "info",
            "ts": (now - timedelta(minutes=3)).isoformat(),
        }
        for i in range(11)
    ]
    messages.append(
        {"id": "m-ffffffff", "to": "urgent", "kind": "blocked", "ts": now.isoformat()}
    )
    bindings = [
        {
            "address": m["to"],
            "harness": "claude",
            "session_id": m["to"],
            "last_seen": (now - timedelta(hours=1)).isoformat(),
        }
        for m in messages
    ]
    actions = plan({"messages": messages, "bindings": bindings}, now)["actions"]
    assert len(actions) == 10
    assert actions[0]["address"] == "urgent"


def test_explicit_urgent_marker_creates_busy_delivery_action() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    message = {"id": "m-urgent", "to": "worker", "kind": "info", "ts": now.isoformat()}
    state = {
        "messages": [message],
        "events": [
            {
                "message_id": "m-urgent",
                "reader": "worker",
                "event": "urgent",
                "at": now.isoformat(),
            }
        ],
        "bindings": [
            {
                "address": "worker",
                "harness": "paseo",
                "session_id": "s",
                "last_seen": now.isoformat(),
            }
        ],
    }
    action = plan(state, now)["actions"][0]
    assert action["urgent"] is True
    assert action["require_idle"] is False
    assert next_due(state, now) == now


def test_next_due_includes_regular_digest_window() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = {
        "messages": [
            {"id": "m-00000001", "to": "worker", "ts": now.isoformat(), "kind": "info"}
        ],
        "bindings": [
            {"address": "worker", "last_seen": (now - timedelta(hours=1)).isoformat()}
        ],
    }
    assert next_due(state, now) == now + timedelta(minutes=2)


def test_idle_unread_alias_wakes_bound_orchestrator(tmp_path) -> None:
    from varde_workflow.slots import add_alias

    now = datetime(2026, 1, 1, tzinfo=UTC)
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    state = {
        "working": str(tmp_path),
        "messages": [
            {
                "id": "m-idle-unread",
                "to": "plan-a",
                "from": "main",
                "kind": "info",
                "ts": (now - timedelta(minutes=4)).isoformat(),
            }
        ],
        "bindings": [
            {
                "address": "orchestrator-1",
                "harness": "claude",
                "session_id": "orchestrator-session",
                "last_seen": (now - timedelta(minutes=4)).isoformat(),
            }
        ],
    }

    actions = plan(state, now)["actions"]

    assert len(actions) == 1
    assert actions[0]["to"] == "orchestrator-1"
    assert actions[0]["message_ids"] == ["m-idle-unread"]


def test_send_to_orchestrator_and_plan_alias_reaches_live_slot(
    tmp_path, capsys
) -> None:
    from argparse import Namespace

    from varde_workflow.commands.msg import run as run_msg
    from varde_workflow.inbox import read_all
    from varde_workflow.slots import add_alias

    now = datetime.now(UTC) - timedelta(minutes=4)
    add_alias(tmp_path, "orchestrator-2", "plan-live")
    for recipient in ("orchestrator", "orchestrator-2", "plan-live"):
        args = Namespace(
            message_command="send",
            from_address="main",
            to=recipient,
            kind="blocked",
            text=f"role inbox delivery via {recipient}",
            notes=None,
            reply_to=None,
            urgent=False,
        )
        assert run_msg(args, tmp_path) == 0
        output = capsys.readouterr().out
        assert "to orchestrator-2 (no-holder)" in output
    messages = read_all(tmp_path)
    state = {
        "working": str(tmp_path),
        "messages": [
            {
                "id": message.id,
                "to": message.to,
                "from": message.from_,
                "kind": message.kind,
                "text": message.text,
                "ts": now.isoformat(),
            }
            for message in messages
        ],
        "bindings": [
            {
                "address": "orchestrator-2",
                "harness": "claude",
                "session_id": "live-session",
                "last_seen": (now - timedelta(minutes=4)).isoformat(),
            }
        ],
    }

    actions = plan(state, now)["actions"]

    assert len(actions) == 1
    assert actions[0]["to"] == "orchestrator-2"
    assert actions[0]["message_ids"] == [message.id for message in messages]


def test_old_worker_done_without_follow_up_wakes_slot_owner(tmp_path) -> None:
    from varde_workflow.slots import add_alias

    now = datetime(2026, 1, 1, tzinfo=UTC)
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    state = {
        "working": str(tmp_path),
        "messages": [
            {
                "id": "m-worker-done",
                "to": "plan-a",
                "from": "worker-1",
                "kind": "done",
                "ts": (now - timedelta(minutes=4)).isoformat(),
                "text": "worker finished",
            }
        ],
        "bindings": [
            {
                "address": "orchestrator-1",
                "harness": "claude",
                "session_id": "orchestrator-session",
                "last_seen": (now - timedelta(minutes=4)).isoformat(),
            },
            {
                "address": "worker-1",
                "harness": "claude",
                "session_id": "worker-session",
                "last_seen": (now - timedelta(minutes=4)).isoformat(),
            },
        ],
    }

    actions = plan(state, now)["actions"]

    assert len(actions) == 1
    assert actions[0]["to"] == "orchestrator-1"
    assert actions[0]["message_ids"] == ["m-worker-done"]


def test_done_to_arbitrary_owner_obeys_recent_activity_grace(
    tmp_path,
) -> None:
    from varde_workflow.binding import BindingStore

    now = datetime(2026, 1, 1, tzinfo=UTC)
    message = {
        "id": "m-12345678",
        "to": "owner",
        "from": "plan-id",
        "kind": "done",
        "ts": now.isoformat(),
    }
    store = BindingStore(tmp_path)
    marker = store.issue("owner", now=now)
    assert store.redeem(marker, "owner-session", "claude", "/repo", now=now)
    binding = store.list_bindings()[0]
    assert plan({"messages": [message]}, now)["actions"] == []
    assert plan({"messages": [message], "bindings": [binding]}, now)["actions"] == []
    due = now + timedelta(seconds=120)
    recent_binding = binding
    assert next_due({"messages": [message], "bindings": [recent_binding]}, now) == due
    # A real BindingStore record stays active only while last_seen is recent.
    current = store._current(store.addresses / "owner")
    assert current is not None
    key = current["session_key"]
    record_path = store.bindings / f"{key}.json"
    record = __import__("json").loads(record_path.read_text())
    record["last_seen"] = (now - timedelta(minutes=3)).isoformat()
    record_path.write_text(__import__("json").dumps(record))
    binding = store.list_bindings()[0]
    actions = plan({"messages": [message], "bindings": [binding]}, due)["actions"]
    assert actions[0]["to"] == "owner" and actions[0]["tier"] == "regular"


def test_urgent_action_caps_twenty_lines_and_keeps_urgent_before_digest() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    messages = [
        {"id": f"m-{i:08x}", "to": "worker", "kind": "blocked", "ts": now.isoformat()}
        for i in range(21)
    ]
    messages.extend(
        {
            "id": f"m-{i + 20:08x}",
            "to": "worker",
            "kind": "info",
            "ts": (now - timedelta(minutes=3)).isoformat(),
        }
        for i in range(2)
    )
    bindings = [
        {
            "address": "worker",
            "harness": "claude",
            "session_id": "s",
            "last_seen": (now - timedelta(hours=1)).isoformat(),
        }
    ]
    actions = plan({"messages": messages, "bindings": bindings}, now)["actions"]
    assert actions[0]["message_ids"] == [message["id"] for message in messages[:20]]


def test_one_recipient_action_orders_two_urgent_messages_before_digest() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    messages = [
        {
            "id": "m-00000001",
            "to": "worker",
            "kind": "needs-user",
            "ts": (now - timedelta(minutes=2)).isoformat(),
        },
        {
            "id": "m-00000002",
            "to": "worker",
            "kind": "blocked",
            "ts": (now - timedelta(minutes=1)).isoformat(),
        },
        {
            "id": "m-00000003",
            "to": "worker",
            "kind": "info",
            "ts": (now - timedelta(minutes=3)).isoformat(),
        },
    ]
    actions = plan(
        {
            "messages": messages,
            "bindings": [
                {
                    "address": "worker",
                    "harness": "claude",
                    "last_seen": (now - timedelta(hours=1)).isoformat(),
                }
            ],
        },
        now,
    )["actions"]
    assert len(actions) == 1
    assert actions[0]["message_ids"] == ["m-00000001", "m-00000002", "m-00000003"]


def test_unbound_is_held_and_done_is_urgent_only_on_plan_owner_route(tmp_path) -> None:
    from varde_workflow.binding import BindingStore

    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = BindingStore(tmp_path)
    marker = store.issue("orchestrator-1", now=now)
    assert store.redeem(
        marker,
        "owner-session",
        "claude",
        "/repo",
        now=now - timedelta(minutes=5),
    )
    binding = store.list_bindings()[0]
    agent_marker = store.issue("other-agent", now=now)
    assert store.redeem(
        agent_marker, "agent-session", "claude", "/repo", now=now - timedelta(minutes=5)
    )
    agent_binding = next(
        item for item in store.list_bindings() if item["address"] == "other-agent"
    )
    owner_done = {
        "id": "m-00000001",
        "to": "orchestrator-1",
        "from": "plan-id",
        "kind": "done",
        "ts": (now - timedelta(minutes=3)).isoformat(),
        "text": "done",
    }
    other_done = {
        **owner_done,
        "id": "m-00000002",
        "to": "other-agent",
        "from": "orchestrator-1",
    }
    unbound = {
        **owner_done,
        "id": "m-00000003",
        "to": "missing",
        "kind": "blocked",
        "ts": now.isoformat(),
    }
    state = {
        "messages": [owner_done, other_done, unbound],
        "bindings": [binding, agent_binding],
    }
    result = plan(state, now)
    action = next(item for item in result["actions"] if item["tier"] == "urgent")
    assert action["message_ids"][0] == owner_done["id"]
    assert action["message_ids"] == [owner_done["id"]]
    regular = next(item for item in result["actions"] if item["tier"] == "regular")
    assert regular["to"] == "other-agent"
    assert regular["message_ids"] == [other_done["id"]]
    assert {
        "to",
        "tier",
        "message_ids",
        "wake",
        "require_idle",
        "prompt",
    } <= action.keys()
    from varde_workflow.relay_state import lease_actions

    leased = lease_actions(tmp_path, [action], "mailman-token", now)[0]
    assert leased["prompt"].splitlines()[0] == (
        f"[varde-delivery: {leased['action_id']} orchestrator-1]"
    )
    assert (
        "Acknowledge with `varde msg ack m-00000001 --as orchestrator-1`."
        in leased["prompt"]
    )
    assert "`varde msg ack m-00000002 --as other-agent`." in regular["prompt"]
    assert "missing" not in {item["to"] for item in result["actions"]}
    assert next_due({"messages": [unbound]}, now) == now + timedelta(minutes=2)
    due_result = plan({"messages": [unbound]}, now + timedelta(minutes=2))
    assert due_result["escalations"] == [{"to": "main", "message_id": unbound["id"]}]
    store.resolve_reader("claude", "owner-session", "", {}, now)
    fresh_binding = next(
        item for item in store.list_bindings() if item["address"] == "orchestrator-1"
    )
    fresh_message = {**owner_done, "id": "m-00000004", "ts": now.isoformat()}
    refreshed = plan({"messages": [fresh_message], "bindings": [fresh_binding]}, now)
    assert refreshed["actions"][0]["message_ids"] == [fresh_message["id"]]
    assert refreshed["actions"][0]["to"] == "orchestrator-1"


def test_main_retries_after_three_failed_events_at_final_backoff():
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    message = {
        "id": "m-main-retry",
        "to": "main",
        "from": "worker",
        "kind": "needs-user",
        "ts": (now - timedelta(hours=1)).isoformat(),
    }
    events = [
        {
            "event": "failed",
            "message_id": message["id"],
            "at": (now - timedelta(minutes=45)).isoformat(),
        },
        {
            "event": "failed",
            "message_id": message["id"],
            "at": (now - timedelta(minutes=43)).isoformat(),
        },
        {
            "event": "failed",
            "message_id": message["id"],
            "at": (now - timedelta(minutes=38)).isoformat(),
        },
    ]
    state = {
        "messages": [message],
        "events": events,
        "bindings": [
            {
                "address": "main",
                "harness": "claude",
                "last_seen": (now - timedelta(hours=2)).isoformat(),
                "wake_context": {"paseo_id": "paseo-main"},
            }
        ],
    }

    actions = plan(state, now)["actions"]

    assert len(actions) == 1
    assert actions[0]["to"] == "main"


def test_main_is_not_planned_inside_final_backoff_after_three_failures():
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    message = {
        "id": "m-main-backoff",
        "to": "main",
        "from": "worker",
        "kind": "needs-user",
        "ts": (now - timedelta(hours=1)).isoformat(),
    }
    events = [
        {
            "event": "failed",
            "message_id": message["id"],
            "at": (now - delta).isoformat(),
        }
        for delta in (
            timedelta(minutes=20),
            timedelta(minutes=18),
            timedelta(minutes=5),
        )
    ]
    state = {
        "messages": [message],
        "events": events,
        "bindings": [
            {
                "address": "main",
                "harness": "claude",
                "last_seen": (now - timedelta(hours=2)).isoformat(),
                "wake_context": {"paseo_id": "paseo-main"},
            }
        ],
    }

    assert plan(state, now)["actions"] == []


def test_relay_wake_keeps_native_identity_and_legacy_paseo_id():
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    state = {
        "messages": [
            {
                "id": "m1",
                "to": "worker",
                "from": "main",
                "kind": "needs-user",
                "text": "wake",
                "ts": (now - timedelta(minutes=3)).isoformat(),
            }
        ],
        "events": [],
        "bindings": [
            {
                "address": "worker",
                "harness": "claude",
                "session_id": "s",
                "cwd": "/repo",
                "last_seen": (now - timedelta(minutes=3)).isoformat(),
                "wake_context": {
                    "harness": "claude-cli",
                    "agent_id": "agent-1",
                    "runner_endpoint": "http://runner",
                    "paseo_id": "paseo-1",
                },
            }
        ],
    }

    wake = plan(state, now)["actions"][0]["wake"]

    assert wake["harness"] == "claude-cli"
    assert wake["agent_id"] == "agent-1"
    assert wake["runner_endpoint"] == "http://runner"
    assert wake["paseo_id"] == "paseo-1"


def test_relay_wake_reads_legacy_paseo_agent_id():
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    state = {
        "messages": [
            {
                "id": "m1",
                "to": "worker",
                "from": "main",
                "kind": "needs-user",
                "text": "wake",
                "ts": (now - timedelta(minutes=3)).isoformat(),
            }
        ],
        "events": [],
        "bindings": [
            {
                "address": "worker",
                "harness": "claude",
                "last_seen": (now - timedelta(minutes=3)).isoformat(),
                "wake_context": {"paseo_agent_id": "legacy-agent"},
            }
        ],
    }

    assert plan(state, now)["actions"][0]["wake"]["paseo_id"] == "legacy-agent"
