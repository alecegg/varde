from pathlib import Path

import pytest
from varde_core.layout import agent_dirs, project_dirs, skill_dirs


def _skill(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("# Skill\n")


def test_skill_dirs_finds_module_symlink(tmp_path: Path) -> None:
    module_skills = tmp_path / "m" / "src" / "m_pkg" / "skills"
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "pyproject.toml").write_text('[project]\nname = "varde-module"\n')
    _skill(module_skills / "varde-module")
    (tmp_path / "m" / "skills").symlink_to(module_skills, target_is_directory=True)

    assert skill_dirs(tmp_path) == {
        "varde-module": tmp_path / "m" / "skills" / "varde-module",
    }


def test_skill_dirs_rejects_duplicate_names(tmp_path: Path) -> None:
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "pyproject.toml").write_text('[project]\nname = "module"\n')
    _skill(tmp_path / "m" / "skills" / "varde-same")

    (tmp_path / "n").mkdir()
    (tmp_path / "n" / "pyproject.toml").write_text('[project]\nname = "n"\n')
    _skill(tmp_path / "n" / "skills" / "varde-same")

    with pytest.raises(ValueError, match="duplicate varde-same") as error:
        skill_dirs(tmp_path)
    assert str(tmp_path / "m" / "skills" / "varde-same") in str(error.value)
    assert str(tmp_path / "n" / "skills" / "varde-same") in str(error.value)


def test_agent_and_project_discovery(tmp_path: Path) -> None:
    (tmp_path / "m" / "agents" / "varde-reviewer").mkdir(parents=True)
    project = tmp_path / "m" / "pyproject.toml"
    project.parent.mkdir(exist_ok=True)
    project.write_text('[project]\nname = "varde-module"\n')
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "pyproject.toml").write_text('[project]\nname="hidden"')
    (tmp_path / "pyproject.toml").write_text('[project]\nname="root"')

    assert agent_dirs(tmp_path) == {
        "varde-reviewer": tmp_path / "m" / "agents" / "varde-reviewer",
    }
    assert project_dirs(tmp_path) == {"varde-module": tmp_path / "m"}
