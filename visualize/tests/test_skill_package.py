"""The visualize module ships exactly its one skill."""

from __future__ import annotations

from importlib.resources import files


def test_package_ships_varde_visualize_skill() -> None:
    skills = files("varde_visualize") / "skills"
    names = {path.name for path in skills.iterdir() if path.is_dir()}
    assert names == {"varde-visualize"}
    skill = skills / "varde-visualize" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: varde-visualize\n")


CRAFT_CAP_BYTES = 2400


def test_craft_reference_exists_under_cap_and_is_linked() -> None:
    skill_dir = files("varde_visualize") / "skills" / "varde-visualize"
    craft = skill_dir / "references" / "craft.md"
    assert len(craft.read_bytes()) <= CRAFT_CAP_BYTES
    assert "references/craft.md" in (skill_dir / "SKILL.md").read_text()
