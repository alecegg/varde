from varde_runner.config import ROLE_NAMES
from varde_runner.identity_groups import group
from varde_runner.identity_profile import defaults
from varde_runner.registry import SessionBinding


def test_group_counts_expands_orchestrators_and_uses_worst_state():
    rows = [
        {
            "session_id": "b1",
            "agent_id": "builder-one",
            "role": "builder",
            "workspace": "repo",
            "lifecycle": "idle",
        },
        {
            "session_id": "b2",
            "agent_id": "builder-two",
            "role": "builder",
            "workspace": "repo",
            "lifecycle": "failed",
        },
        {
            "session_id": "o1",
            "agent_id": "orch",
            "role": "orchestrator",
            "lifecycle": "running",
        },
        {
            "session_id": "m1",
            "agent_id": "bot",
            "role": "manager-bot",
            "lifecycle": "awaiting_question",
        },
        {
            "session_id": "x1",
            "agent_id": "unknown",
            "role": "mailman",
            "lifecycle": "running",
        },
        {"session_id": "x2", "agent_id": "null", "role": None, "lifecycle": "running"},
        {
            "session_id": "done",
            "agent_id": "done",
            "role": "builder",
            "lifecycle": "completed",
        },
    ]
    bindings = {
        "o1": SessionBinding(
            "address", "fake", "adapter", "o1", "orchestrator", "plan-a"
        )
    }

    result = {
        entry["id"]: entry for entry in group(rows, bindings, defaults(ROLE_NAMES))
    }

    assert result["builder"]["count"] == 2
    assert len(result["builder"]["instances"]) == 2
    assert result["builder"]["worst_state"] == "failed"
    assert result["orchestrator"]["instances"][0]["label"] == "plan-a"
    assert result["manager"]["worst_state"] == "needs you"
    assert result["other"]["count"] == 2


def test_needs_you_failed_starting_and_idle_status_states():
    rows = [
        {
            "agent_id": "pending",
            "role": "builder",
            "lifecycle": "running",
            "pending_requests": [{}],
        },
        {
            "agent_id": "permission",
            "role": "builder",
            "lifecycle": "awaiting_permission",
        },
        {
            "agent_id": "idle-status",
            "role": "builder",
            "lifecycle": "running",
            "idle_status": "awaiting_question",
        },
        {"agent_id": "limited", "role": "builder", "lifecycle": "rate_limited"},
        {"agent_id": "starting", "role": "builder", "lifecycle": "starting"},
        {"agent_id": "idle", "role": "builder", "lifecycle": "idle"},
    ]
    result = {entry["id"]: entry for entry in group(rows, {}, defaults(ROLE_NAMES))}
    assert [instance["state"] for instance in result["builder"]["instances"]] == [
        "needs you",
        "needs you",
        "needs you",
        "failed",
        "running",
        "idle",
    ]


def test_duplicate_labels_use_role_name_and_creation_order():
    rows = [
        {
            "session_id": "one",
            "agent_id": "instance-12345678",
            "role": "orchestrator",
            "workspace": "same",
            "lifecycle": "running",
        },
        {
            "session_id": "two",
            "agent_id": "instance-abcdefgh",
            "role": "orchestrator",
            "workspace": "same",
            "lifecycle": "running",
        },
    ]
    result = {entry["id"]: entry for entry in group(rows, {}, defaults(ROLE_NAMES))}
    assert [item["label"] for item in result["orchestrator"]["instances"]] == [
        "Orchestrator 1",
        "Orchestrator 2",
    ]
