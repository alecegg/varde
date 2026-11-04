from types import SimpleNamespace

from varde_runner.config import ROLE_NAMES
from varde_runner.identity_profile import defaults
from varde_runner.registry import SessionBinding
from varde_runner.role_queue_source import read_role_queue


def builder_sources(agent_rows, plans=()):
    return SimpleNamespace(
        queue_inputs=lambda: ({"plans": list(plans)}, []),
        agent_rows=agent_rows,
        bindings={},
        profiles=defaults(ROLE_NAMES),
    )


def builder_agent(agent_id, *, pending=False, lifecycle=None):
    return {
        "session_id": f"session-{agent_id}",
        "agent_id": agent_id,
        "role": "builder",
        "lifecycle": lifecycle or ("awaiting_permission" if pending else "idle"),
        "pending_requests": [{"request_id": "req-1"}] if pending else [],
    }


def builder_summary(agent_rows, plans=()):
    result = read_role_queue(builder_sources(agent_rows, plans))
    return next(summary for summary in result.roles if summary.role == "builder")


def test_needs_you_counts_a_pending_approval_without_a_blocked_row():
    builder = builder_summary([builder_agent("agent-1", pending=True)])

    assert builder.needs_you == 1
    assert builder.state == "needs_you"


def test_needs_you_counts_each_pending_request_on_one_agent():
    agent = builder_agent("agent-1", pending=True)
    agent["pending_requests"] = [
        {"request_id": "req-1"},
        {"request_id": "req-2"},
    ]

    builder = builder_summary([agent])

    assert builder.needs_you == 2


def test_needs_you_counts_instance_without_a_request_list_once():
    agent = builder_agent("agent-1", pending=True)
    del agent["pending_requests"]

    builder = builder_summary([agent])

    assert builder.needs_you == 1


def test_needs_you_counts_each_pending_agent_and_each_blocked_row():
    plans = [
        {"id": "blocked-plan", "assigned_to": "builder", "status": "blocked"},
    ]

    both_pending = builder_summary(
        [builder_agent("agent-1", pending=True), builder_agent("agent-2", pending=True)]
    )
    pending_plus_blocked = builder_summary(
        [builder_agent("agent-1", pending=True)], plans
    )

    assert both_pending.needs_you == 2
    assert pending_plus_blocked.needs_you == 2


def test_needs_you_is_zero_without_approvals_or_blocked_rows():
    builder = builder_summary([builder_agent("agent-1")])

    assert builder.needs_you == 0
    assert builder.state == "idle"


def test_failed_agent_with_a_running_item_makes_the_role_failed():
    plans = [
        {
            "id": "running-plan",
            "title": "Add role status card",
            "assigned_to": "builder",
            "status": "active",
        },
    ]

    builder = builder_summary([builder_agent("agent-1", lifecycle="failed")], plans)

    assert builder.state == "failed"
    assert builder.current is not None
    assert builder.current.title == "Add role status card"


def test_failed_agent_without_queue_rows_is_still_failed():
    builder = builder_summary([builder_agent("agent-1", lifecycle="failed")])

    assert builder.state == "failed"
    assert builder.current is None


def test_pending_approval_outranks_a_failed_agent():
    builder = builder_summary(
        [
            builder_agent("agent-1", pending=True),
            builder_agent("agent-2", lifecycle="failed"),
        ]
    )

    assert builder.state == "needs_you"


def test_read_role_queue_maps_assigned_plan_and_identity_snapshot():
    sources = SimpleNamespace(
        queue_inputs=lambda: (
            {
                "plans": [
                    {
                        "id": "queue-plan",
                        "title": "Queue plan",
                        "assigned_to": "builder",
                        "status": "active",
                    },
                    {
                        "id": "next-plan",
                        "assigned_to": "builder",
                        "status": "backlog",
                    },
                ]
            },
            [],
        ),
        agent_rows=[
            {
                "session_id": "session-1",
                "agent_id": "agent-1",
                "role": "builder",
                "lifecycle": "running",
            }
        ],
        bindings={
            "session-1": SessionBinding(
                "address", "fake", "adapter", "session-1", "builder"
            )
        },
        profiles=defaults(ROLE_NAMES),
    )

    result = read_role_queue(sources)

    builder = next(summary for summary in result.roles if summary.role == "builder")
    assert builder.agent_id == "agent-1"
    assert builder.state == "running"
    assert builder.current is not None
    assert builder.current.title == "Queue plan"
    assert builder.queued == 1
    assert [row.id for row in result.rows["builder"]] == ["queue-plan", "next-plan"]
