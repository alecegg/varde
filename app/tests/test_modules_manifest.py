from importlib.metadata import entry_points
from importlib.resources import files
from typing import NamedTuple

from varde.manifest import Manifest, install_closure
from varde.setup import catalog


class ModuleRow(NamedTuple):
    distribution: str
    import_package: str
    skills: tuple[str, ...]
    agents: tuple[str, ...]
    requires: tuple[str, ...]


AGENT_VARIANTS = ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md")

MODULES = {
    "core": ModuleRow("varde-core", "varde_core", (), (), ()),
    "toz": ModuleRow("varde-toz", "varde_toz", ("varde-toz",), (), ()),
    "code": ModuleRow(
        "varde-code",
        "varde_code",
        ("varde-code", "varde-scan", "varde-customize"),
        (),
        (),
    ),
    "learn": ModuleRow(
        "varde-learn",
        "varde_learn",
        (
            "varde-learn",
            "varde-diagnose",
            "varde-improve",
            "varde-knowledge",
            "varde-session-notes",
            "varde-docs",
            "varde-skill-authoring",
            "varde-doc-authoring",
        ),
        (),
        (),
    ),
    "workflow": ModuleRow(
        "varde-workflow",
        "varde_workflow",
        (
            "varde-plan",
            "varde-build",
            "varde-orchestrate",
            "varde-swarm",
            "varde-review",
            "varde-review-ui",
            "varde-verify",
        ),
        (
            "accessibility",
            "readability",
            "spec-adherence",
            "ux-advocate",
            "varde-planner",
            "varde-builder",
            "varde-reviewer",
            "varde-explorer",
        ),
        ("code", "toz", "learn", "dev", "visualize"),
    ),
    "dev": ModuleRow(
        "varde-dev",
        "varde_dev",
        (
            "varde-prototype",
            "varde-explore",
            "varde-explain",
            "varde-pr",
        ),
        (),
        (),
    ),
    "visualize": ModuleRow(
        "varde-visualize", "varde_visualize", ("varde-visualize",), (), ()
    ),
    "design": ModuleRow("varde-design", "varde_design", ("varde-design",), (), ()),
    "app": ModuleRow("varde", "varde", ("varde-manage",), (), ()),
}


def test_manifest_table_and_current_provider() -> None:
    known = set(MODULES)
    providers = {point.name: point for point in entry_points(group="varde.skills")}
    agent_providers = {
        point.name: point for point in entry_points(group="varde.agents")
    }
    manifests = catalog.module_manifests()
    assert set(manifests) == known
    for module, row in MODULES.items():
        distribution, import_package = row.distribution, row.import_package
        skill_names, agent_names, requires = row.skills, row.agents, row.requires
        assert set(requires) <= known
        assert module in providers
        provider = providers[module]
        assert provider is not None
        assert provider.value == import_package
        assert provider.dist is not None
        assert provider.dist.name == distribution
        manifest = manifests[module]
        assert manifest is not None
        assert manifest.name == module
        assert set(manifest.requires) == set(requires)
        package = files(provider.value)
        actual_skills = {
            path.name
            for path in (package / "skills").iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        assert actual_skills == set(skill_names)
        actual_agents = (
            {
                path.name
                for path in (package / "agents").iterdir()
                if path.is_dir()
                and any((path / name).is_file() for name in AGENT_VARIANTS)
            }
            if (package / "agents").is_dir()
            else set()
        )
        assert actual_agents == set(agent_names)
        if agent_names:
            provider = agent_providers[module]
            assert provider is not None
            assert provider.value == import_package
            assert provider.dist is not None
            assert provider.dist.name == distribution


def test_workflow_install_closure_from_literal_module_table() -> None:
    manifests = {name: Manifest(name, row.requires) for name, row in MODULES.items()}
    assert install_closure("workflow", manifests) == (
        "code",
        "dev",
        "learn",
        "toz",
        "visualize",
        "workflow",
    )
