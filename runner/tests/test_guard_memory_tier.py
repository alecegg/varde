from varde_runner.guard_memory_tier import classify_memory_write
from varde_runner.guard_policy import must_escalate, verdict


def test_classifies_known_agent_memory_tiers():
    cases = {
        "/home/alec/source/agent-memory/general/preferences.md": "user",
        "/home/alec/source/agent-memory/projects/demo/notes.md": "project",
        "/home/alec/source/agent-memory/agents/codex/notes.md": "role",
    }
    for path, tier in cases.items():
        assert classify_memory_write({"path": path}) == {
            "outcome": "decide",
            "target_tier": tier,
            "reason": f"agent-memory path belongs to the {tier} tier",
        }


def test_flags_unknown_agent_memory_tier_and_ignores_other_paths():
    assert classify_memory_write({"file_path": "/x/agent-memory/unknown/a.md"}) == {
        "outcome": "flag",
        "target_tier": None,
        "reason": "agent-memory path has an unclear tier",
    }
    assert classify_memory_write({"path": "/workspace/notes.md"}) is None


def test_policy_escalates_unclear_memory_tier_and_keeps_clear_paths_on_policy():
    assert (
        must_escalate("path_scope", {"path": "/x/agent-memory/unknown/a.md"}, "/x")
        == "agent-memory path has an unclear tier"
    )
    assert (
        must_escalate(
            "path_scope", {"path": "/x/agent-memory/projects/demo/a.md"}, "/x"
        )
        is None
    )


def test_verdict_still_requires_allowlist_for_clear_memory_tier():
    result = verdict(
        "path_scope",
        {"path": "/workspace/agent-memory/projects/demo/a.md"},
        "/workspace",
        set(),
    )
    assert result["verdict"] == "escalate"
    assert result["reason"] == "no allowlist match"
