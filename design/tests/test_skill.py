"""varde-design SKILL.md: size caps, loading rule and project neutrality."""

import re
from pathlib import Path

import pytest

SKILL = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "varde_design"
    / "skills"
    / "varde-design"
)
SKILL_MD = SKILL / "SKILL.md"
SKILL_BYTE_CAP = 2000
TEXT_SUFFIXES = {".md", ".html", ".css"}
# Skill, command and config-file names are the only allowed Varde strings.
ALLOWED = re.compile(
    r"varde-design\.toml|varde-design|varde design"
    r"|varde-prototype|varde-review|varde-visualize"
)
FORBIDDEN = (
    "varde",
    "runner",
    "ui-ux-standards",
    "doc-serve",
    "style.css",
    "lib/ui",
    "_catalog",
    "--cf-",
    "a/b test",
    "blind",
)


# FLOW.md is generated for human readers and names the generating command.
def _shipped_text_files() -> list[Path]:
    return sorted(
        p
        for p in SKILL.rglob("*")
        if p.is_file() and p.suffix in TEXT_SUFFIXES and p.name != "FLOW.md"
    )


def test_skill_md_is_within_the_byte_cap() -> None:
    assert len(SKILL_MD.read_bytes()) <= SKILL_BYTE_CAP


def test_skill_md_token_estimate_is_within_500() -> None:
    assert len(SKILL_MD.read_bytes()) / 4 <= 500


def test_frontmatter_has_name_description_and_recommends() -> None:
    head = SKILL_MD.read_text(encoding="utf-8").split("---")[1]
    assert "name: varde-design" in head
    assert re.search(r'^description: ".+"$', head, re.MULTILINE)
    assert re.search(r"^recommends: \[.+\]$", head, re.MULTILINE)


def test_reference_layer_is_flat_and_every_link_resolves() -> None:
    assert not [p for p in (SKILL / "references").rglob("*") if p.is_dir()]
    text = SKILL_MD.read_text(encoding="utf-8")
    names = set(re.findall(r"references/([\w-]+\.md)", text))
    names |= {f"{n}.md" for n in re.findall(r"`(page-[a-z]+)\.md`", text)}
    assert names
    missing = [n for n in names if not (SKILL / "references" / n).is_file()]
    assert missing == []


def test_only_the_floor_is_loaded_unconditionally() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Read `references/floor.md` before the first UI edit" in text
    assert text.count("Read `references/") == 1


def test_cli_steps_are_conditional_on_help_succeeding() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "varde design --help" in text
    assert "varde design survey" in text
    assert "varde design check" in text


def test_critique_reference_names_verdicts_and_capture_fallbacks() -> None:
    text = (SKILL / "references" / "review.md").read_text(encoding="utf-8")
    assert all(word in text for word in ("ship", "fix", "rebuild", "recapture"))
    assert "Playwright" in text
    assert "not independent" in text


@pytest.mark.parametrize("path", _shipped_text_files(), ids=lambda p: p.name)
def test_skill_files_carry_no_project_specific_strings(path: Path) -> None:
    text = ALLOWED.sub("", path.read_text(encoding="utf-8")).lower()
    hits = [term for term in FORBIDDEN if term in text]
    assert hits == []
