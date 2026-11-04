from pathlib import Path

import pytest
from varde.setup import catalog
from varde.setup.catalog import Skill, SkillFile
from varde.setup.sync.skills import OWNERSHIP_MARKER, install_canonical
from varde_core import skill_props

REGISTRY = """[[tool]]
skill = "varde-x"
step = "go"
entry = "varde-x/go.py"

[[tool]]
skill = "varde-y"
step = "other"
entry = "varde-y/other.py"
"""


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "pkg"
    (root / "how" / "varde-x").mkdir(parents=True)
    (root / "how" / "varde-x" / "go.md").write_text("topic v1")
    (root / "step_tools" / "varde-x").mkdir(parents=True)
    (root / "step_tools" / "varde-x" / "go.py").write_text("def run(a): return 0\n")
    (root / "step_tools" / "registry.toml").write_text(REGISTRY)
    return root


def _skill(package: Path, name: str = "varde-x") -> Skill:
    base = Skill(name, (SkillFile("SKILL.md", b"skill", False),))
    return catalog._with_extras(base, [package])


def _names(skill: Skill) -> set[str]:
    return {file.relative_path for file in skill.files}


def test_files_are_installed_with_only_the_skills_rows(package):
    skill = _skill(package)
    assert _names(skill) == {
        "SKILL.md",
        "how/go.md",
        "step_tools/registry.toml",
        "step_tools/varde-x/go.py",
    }
    registry = next(
        f for f in skill.files if f.relative_path == "step_tools/registry.toml"
    )
    text = registry.bytes.decode()
    assert 'skill = "varde-x"' in text
    assert "varde-y" not in text


def test_skill_without_steps_gets_nothing(package):
    assert _names(_skill(package, "varde-z")) == {"SKILL.md"}


def test_install_writes_files_and_hash_changes_with_topic(package, tmp_path):
    target = tmp_path / "sync"
    install_canonical(target, (_skill(package),))
    assert (target / "varde-x" / "how" / "go.md").read_text() == "topic v1"
    assert (target / "varde-x" / "step_tools" / "varde-x" / "go.py").is_file()
    first = skill_props.parse((target / "varde-x" / OWNERSHIP_MARKER).read_text())
    (package / "how" / "varde-x" / "go.md").write_text("topic v2")
    install_canonical(target, (_skill(package),))
    assert (target / "varde-x" / "how" / "go.md").read_text() == "topic v2"
    second = skill_props.parse((target / "varde-x" / OWNERSHIP_MARKER).read_text())
    assert second.packaged_hash != first.packaged_hash


def test_locally_edited_topic_survives_sync(package, tmp_path):
    target = tmp_path / "sync"
    install_canonical(target, (_skill(package),))
    (target / "varde-x" / "how" / "go.md").write_text("mine")
    (package / "how" / "varde-x" / "go.md").write_text("topic v2")
    install_canonical(target, (_skill(package),))
    assert (target / "varde-x" / "how" / "go.md").read_text() == "mine"
    props = skill_props.parse((target / "varde-x" / OWNERSHIP_MARKER).read_text())
    assert props.pending_hash


def test_real_catalog_carries_how_topics():
    docs = next(skill for skill in catalog.skills() if skill.name == "varde-docs")
    assert any(file.relative_path.startswith("how/") for file in docs.files)
    plan = next(skill for skill in catalog.skills() if skill.name == "varde-plan")
    assert not any(file.relative_path.startswith("step_tools/") for file in plan.files)
