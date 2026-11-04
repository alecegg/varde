from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.loop.output import OutputHarness
from varde_learn.loop.output.command import OutputRequest, run_output

_SKILLS_MARKER = "Skills available for this suite (names only): "


def _skill(root: Path, name: str, requires: str = "") -> Path:
    skill = root / name
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\n{requires}\n---\n")
    (skill / "evals/evals.json").write_text(json.dumps({"evals": [{"prompt": "test"}]}))
    return skill


def _suite_skills(skill: Path) -> list[str]:
    prompts: list[str] = []
    run_output(
        OutputRequest(skill, OutputHarness.CODEX, no_baseline=True),
        runner=lambda call: (prompts.append(call.prompt), ({}, 0, 0))[1],
    )
    assert len(prompts) == 1
    line = next(
        line for line in prompts[0].splitlines() if line.startswith(_SKILLS_MARKER)
    )
    return line.removeprefix(_SKILLS_MARKER).removesuffix(".").split(", ")


def test_default_suite_skills_include_required_dependency_closure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    _skill(root, "varde-learn", "requires: [varde-code]\n")
    _skill(root, "varde-code", "requires: [varde-review]\n")
    _skill(root, "varde-review")
    assert _suite_skills(root / "varde-learn") == [
        "varde-code",
        "varde-learn",
        "varde-review",
    ]


def test_missing_required_skill_error_names_skill_and_root(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = _skill(root, "varde-learn", "requires: [varde-missing]\n")
    with pytest.raises(ValueError) as raised:
        _suite_skills(skill)
    assert "varde-missing" in str(raised.value)
    assert str(root) in str(raised.value)
    assert "No such file" in str(raised.value)


def test_malformed_requires_error_names_skill_and_root(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = _skill(root, "varde-learn", "requires: [unfinished\n")
    with pytest.raises(ValueError) as raised:
        _suite_skills(skill)
    assert "varde-learn" in str(raised.value)
    assert str(root) in str(raised.value)
    assert "flow list" in str(raised.value)


def test_explicit_suite_skill_list_is_preserved(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "varde-learn")
    (skill / "evals/evals.json").write_text(
        json.dumps({"skills": ["varde-toz"], "evals": [{"prompt": "test"}]})
    )
    assert _suite_skills(skill) == ["varde-toz"]


def test_explicit_suite_skill_list_rejects_non_string_entry(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "varde-learn")
    (skill / "evals/evals.json").write_text(
        json.dumps({"skills": ["varde-toz", 7], "evals": [{"prompt": "test"}]})
    )
    with pytest.raises(ValueError, match=r"skills\[1\].*must be a string"):
        _suite_skills(skill)
