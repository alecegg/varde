"""Byte caps and rule-ID checks for the varde-design reference files."""

import re
from pathlib import Path

import pytest
from varde_design.registry import RULES_BY_ID, active_rules

REFERENCES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "varde_design"
    / "skills"
    / "varde-design"
    / "references"
)
PAGE_TYPES = ("page-app", "page-form", "page-read", "page-landing")
BYTE_CAPS = {
    **dict.fromkeys(PAGE_TYPES, 6000),
    "craft": 5200,
    "floor": 2400,
    "review": 2800,
}
RULE_ID = re.compile(r"\b[SR]\d{1,2}\b")


def _text(name: str) -> str:
    return (REFERENCES / f"{name}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(BYTE_CAPS))
def test_reference_is_within_its_byte_cap(name: str) -> None:
    assert len(_text(name).encode("utf-8")) <= BYTE_CAPS[name]


@pytest.mark.parametrize("name", sorted(BYTE_CAPS))
def test_rule_ids_named_exist_in_the_registry(name: str) -> None:
    unknown = set(RULE_ID.findall(_text(name))) - set(RULES_BY_ID)
    assert not unknown


@pytest.mark.parametrize("name", PAGE_TYPES)
def test_page_type_names_checker_rules(name: str) -> None:
    text = _text(name)
    assert RULE_ID.search(text)


def test_every_reference_file_has_a_cap() -> None:
    assert {path.stem for path in REFERENCES.glob("*.md")} == set(BYTE_CAPS)


def test_references_have_no_remote_urls() -> None:
    for name in BYTE_CAPS:
        assert "http" not in _text(name)


def test_floor_ids_equal_the_core_profile_ids() -> None:
    core_ids = {rule.id for rule in active_rules("core")}
    assert set(RULE_ID.findall(_text("floor"))) == core_ids
