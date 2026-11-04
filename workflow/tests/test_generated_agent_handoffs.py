from pathlib import Path

AGENTS = Path(__file__).parents[1] / "src" / "varde_workflow" / "agents"
HANDOFF = "When the brief names an orchestrator slot, finish with"
ROLES = ("varde-builder", "varde-reviewer", "varde-explorer", "varde-planner")


def test_generated_agents_require_completion_mail() -> None:
    for role in ROLES:
        files = list((AGENTS / role).glob("*.md")) + list(
            (AGENTS / role).glob("*.toml")
        )
        assert files
        assert all(HANDOFF in path.read_text() for path in files), role
