"""Recap and plan recipe: example pages, help text, `recommended` on choices."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages import blocks
from varde_learn.docs.pages.blocks_render.inputs import (
    choice_answer_schema,
    render_choice,
)
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures"
RECIPES = FIXTURES / "recipes"
PAGES = ("recap", "plan")
STATEMENT = re.compile(r"^[a-z][a-z0-9-]* = ([a-z][a-z0-9-]*)\(", re.MULTILINE)
RECIPE_NAMES = [
    *("wireframe", "columns", "data-model", "endpoint", "file-tree", "tabs", "diff"),
    *("annotated-code", "checklist", "stats", "matrix", "callout", "risks", "form"),
    *("choice", "diagram", "sequence"),
]


def recipe_section() -> str:
    text = files("varde_learn.docs").joinpath("help", "blocks.txt").read_text()
    return text[text.index("Recipes - ") :]


def options(*flags: bool) -> list[object]:
    return [{"label": f"O{i}", "recommended": f} for i, f in enumerate(flags)]


@pytest.mark.parametrize("name", PAGES)
def test_example_pages_check_clean_and_render(name: str) -> None:
    doc = (RECIPES / f"{name}.md").read_text()
    assert blocks.check(doc, RECIPES) == []
    body = render_page(doc, f"{name}.md").body
    assert "vb-error" not in body and "<script" not in body and "style=" not in body


@pytest.mark.parametrize("name", PAGES)
def test_first_statement_after_the_title_is_one_prose_sentence(name: str) -> None:
    lines = (RECIPES / f"{name}.md").read_text().splitlines()
    assert lines[0].startswith("# ") and lines[1] == ""
    sentence = lines[2]
    assert not sentence.startswith("```") and sentence.endswith(".")
    assert len(re.findall(r"[.!?](?:\s|$)", sentence)) == 1
    assert lines[3] == ""


@pytest.mark.parametrize("name", PAGES)
def test_example_pages_use_only_registered_components(name: str) -> None:
    used = STATEMENT.findall((RECIPES / f"{name}.md").read_text())
    assert used and set(used) <= set(COMPONENTS)


def test_recipe_names_exist_in_the_registry() -> None:
    assert set(RECIPE_NAMES) <= set(COMPONENTS)


def test_recap_page_is_sparse_and_ends_with_the_open_choice() -> None:
    used = STATEMENT.findall((RECIPES / "recap.md").read_text())
    assert used[-1] == "choice" and "stats" in used and "matrix" in used


def test_plan_page_ends_with_the_questions_form() -> None:
    used = STATEMENT.findall((RECIPES / "plan.md").read_text())
    assert used[-1] == "form" and "checklist" in used


def test_help_section_names_the_recipe_components_and_the_samples() -> None:
    section = recipe_section()
    for name in RECIPE_NAMES:
        assert re.search(rf"\b{name}\b", section), name
    assert "fixtures/recipes/recap.md" in section and "plan.md" in section


def test_help_output_carries_the_recipe_section(capsys: pytest.CaptureFixture) -> None:
    assert cli.run(["blocks", "--help"]) == 0
    assert recipe_section() in capsys.readouterr().out


def test_every_component_has_a_help_section(capsys: pytest.CaptureFixture) -> None:
    for name in blocks.COMPONENT_SPECS:
        assert cli.run(["blocks", name]) == 0
        assert capsys.readouterr().out.startswith(f"{name} - ")


def test_recommended_on_two_options_is_a_fault() -> None:
    props = {"question": "Which?", "options": options(True, True)}
    assert blocks.check_props("choice", props, 1)
    assert not blocks.check_props(
        "choice", {**props, "options": options(True, False)}, 1
    )
    assert blocks.check_props(
        "choice", {**props, "options": [{"label": "A", "recommended": "yes"}]}, 1
    )


def test_recommended_renders_a_word_badge_and_a_description() -> None:
    out = render_choice({"question": "Which?", "options": options(False, True)}, "w")
    badge = re.search(r'<span class="choice-rec" id="([^"]+)">Recommended</span>', out)
    assert badge and out.count("choice-rec") == 1
    assert f'aria-describedby="{badge.group(1)}"' in out


def test_answer_schema_ignores_recommended() -> None:
    plain = {"question": "Which?", "options": ["O0", "O1"]}
    marked = {"question": "Which?", "options": options(True, False)}
    assert choice_answer_schema(marked) == choice_answer_schema(plain)


def test_whole_page_fixtures_are_discovered_by_the_matrix() -> None:
    from .widget_matrix.cells import fixture_names

    names = fixture_names()
    assert "rich-recipes-recap.md" in names and "rich-recipes-plan.md" in names


def test_normal_and_stress_fixtures_carry_a_recommended_option() -> None:
    for name in ("normal", "stress"):
        assert (
            '"recommended": true' in (FIXTURES / "widgets" / f"{name}.md").read_text()
        )
