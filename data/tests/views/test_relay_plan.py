from datetime import UTC, datetime, timedelta

from varde_data.views.bindings import annotate_stale_bindings
from varde_data.views.relay_plan import next_due, plan

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_plan_prioritizes_urgent_actions_and_caps_actions() -> None:
    messages = [
        {
            "id": f"m-{i:08x}",
            "to": f"worker{i}",
            "kind": "info",
            "ts": (NOW - timedelta(minutes=3)).isoformat(),
            "text": "regular",
        }
        for i in range(11)
    ]
    messages.append(
        {
            "id": "m-ffffffff",
            "to": "urgent",
            "kind": "blocked",
            "ts": NOW.isoformat(),
            "text": "urgent",
        }
    )
    bindings = [
        {
            "address": row["to"],
            "harness": "claude",
            "session_id": row["to"],
            "last_seen": (NOW - timedelta(hours=1)).isoformat(),
        }
        for row in messages
    ]
    actions = plan({"messages": messages, "bindings": bindings}, NOW)["actions"]
    assert len(actions) == 10
    assert actions[0]["address"] == "urgent"


def test_next_due_includes_digest_window() -> None:
    state = {
        "messages": [
            {"id": "m-00000001", "to": "worker", "ts": NOW.isoformat(), "kind": "info"}
        ],
        "bindings": [
            {"address": "worker", "last_seen": (NOW - timedelta(hours=1)).isoformat()}
        ],
    }
    assert next_due(state, NOW) == NOW + timedelta(minutes=2)


def test_actionable_messages_skip_recent_activity_grace() -> None:
    for kind in ("merge-ready", "done", "decision-needed", "blocked"):
        state = {
            "messages": [
                {
                    "id": "m-00000001",
                    "from": "worker",
                    "to": "main",
                    "kind": kind,
                    "ts": NOW.isoformat(),
                    "text": "action needed",
                }
            ],
            "bindings": [
                {
                    "address": "main",
                    "harness": "codex",
                    "session_id": "main-session",
                    "last_seen": (NOW - timedelta(seconds=1)).isoformat(),
                    "wake_context": {"agent_id": "main-agent"},
                },
                {
                    "address": "worker",
                    "harness": "codex",
                    "session_id": "worker-session",
                    "last_seen": (NOW - timedelta(hours=1)).isoformat(),
                },
            ],
        }

        response = plan(state, NOW)

        assert [action["address"] for action in response["actions"]] == ["main"]
        prompt = response["actions"][0]["prompt"]
        assert prompt.splitlines()[0] == "[varde-delivery: pending main]"
        assert prompt.splitlines()[1] == "Varde messages for main: m-00000001"
        assert prompt.splitlines()[2] == (
            "Acknowledge with `varde msg ack m-00000001 --as main`."
        )


def test_stall_wake_prompt_names_message_id_and_subject() -> None:
    state = {
        "messages": [
            {
                "id": "m-00000002",
                "from": "runner",
                "to": "main",
                "kind": "blocked",
                "ts": NOW.isoformat(),
                "text": "Stall plan-6@1792835656: stalled with open task",
            }
        ],
        "bindings": [
            {
                "address": "main",
                "harness": "codex",
                "session_id": "main-session",
                "last_seen": (NOW - timedelta(hours=1)).isoformat(),
                "wake_context": {"agent_id": "main-agent"},
            }
        ],
    }

    action = plan(state, NOW)["actions"][0]

    assert action["prompt"].splitlines()[0] == "[varde-delivery: pending main]"
    assert action["prompt"].splitlines()[1] == (
        "Varde messages for main: m-00000002; stalled: plan-6@1792835656"
    )
    assert action["prompt"].splitlines()[2] == (
        "Acknowledge with `varde msg ack m-00000002 --as main`."
    )


def test_stale_binding_annotation_copies_and_recognizes_legacy_paseo_key() -> None:
    source = [{"address": "a", "wake_context": {"paseo_agent_id": "archived"}}]
    result = annotate_stale_bindings(source, ["archived"])
    assert result == [{**source[0], "stale": True}]
    assert "stale" not in source[0]
