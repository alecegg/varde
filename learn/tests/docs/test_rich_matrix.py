"""matrix: table conversion, marker, totals, faults, escaping, registration."""

from __future__ import annotations

import html
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props, type_text
from varde_learn.docs.pages.blocks_render.option_matrix import (
    render_matrix,
    table_props,
    totals,
)
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.tables import render_table
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


def sample(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "options": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
        "criteria": [{"id": "x", "label": "Cost"}, {"id": "y", "label": "Speed"}],
        "cells": [["yes", "no"], ["partial", "yes"]],
    }
    return {**data, **extra}


def rules_of(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("matrix", data, 1)]


def test_props_become_table_props_and_the_table_renderer_draws_them() -> None:
    props = table_props(sample())
    assert props["columns"] == ["Criterion", "Alpha", "Beta"]
    assert props["rows"] == [["Cost", "yes", "no"], ["Speed", "partial", "yes"]]
    assert props["types"] == {"Alpha": "status", "Beta": "status"}
    assert props["stack"] is True and "sticky_column" not in props
    out = render_matrix(sample())
    assert out.count("<tr>") == 3 and "vb-status-ok" in out and "vb-status-bad" in out
    assert render_table(props).count("<tr>") == out.count("<tr>")


def test_recommended_marker_text_label_and_border_class() -> None:
    out = render_matrix(sample(recommended="b"))
    assert 'aria-label="Beta, Recommended"' in out
    assert out.count('class="vd-matrix-rec"') == 3
    assert "Recommended: Beta." in out
    assert "Recommended" not in render_matrix(sample())


def test_weighted_totals_are_computed_in_python() -> None:
    weights = sample()
    weights["criteria"][0]["weight"] = 3
    out = render_matrix(weights)
    assert "Weighted total" in out and "7 of 8" in out and "2 of 8" in out
    assert totals([["yes", "no"], ["partial", "yes"]], [3, 1], "verdict") == [
        (7, 8),
        (2, 8),
    ]
    assert "Weighted total" not in render_matrix(sample())


def test_level_scale_gets_glyph_word_and_tone() -> None:
    data = sample(cells=[["high", "low"], ["medium", "high"]])
    out = render_matrix(data)
    assert "vb-status-neutral" not in out
    for glyph, word in (("✓", "high"), ("▲", "medium"), ("✕", "low")):
        assert f'aria-hidden="true">{glyph}</span>{word}</span>' in out


def test_cell_count_fault_names_the_row() -> None:
    bad = sample(cells=[["yes", "no"], ["yes"]])
    found = [e.message for e in check_props("matrix", bad, 1)]
    assert any("cells[2] ('Speed') has 1 cells, expected 2" in m for m in found)
    assert "cells-rows" in rules_of(sample(cells=[["yes", "no"]]))


def test_one_scale_per_matrix() -> None:
    assert "scale" in rules_of(sample(cells=[["yes", "high"], ["no", "low"]]))
    assert rules_of(sample(cells=[["high", "text"], ["low", "free text"]])) == []


def test_props_are_validated() -> None:
    assert rules_of(sample()) == []
    assert rules_of(sample(covers=["x"])) == []
    assert "missing-key" in rules_of({})
    assert "recommended" in rules_of(sample(recommended="nope"))
    assert "duplicate" in rules_of(sample(options=[{"id": "a", "label": "A"}] * 2))
    assert "duplicate" in rules_of(
        sample(options=[{"id": "a", "label": "Criterion"}, {"id": "b", "label": "B"}])
    )
    bad = sample()
    bad["criteria"][0]["weight"] = 6
    assert "type" in rules_of(bad)
    bad["criteria"][0]["weight"] = True
    assert "type" in rules_of(bad)
    assert "limit" in rules_of(
        sample(options=[{"id": f"o{i}", "label": f"O{i}"} for i in range(13)])
    )
    assert "unknown-key" in rules_of(sample(extra=1))


def test_one_option_and_one_criterion_read_correctly() -> None:
    one = {
        "options": [{"id": "a", "label": "Only"}],
        "criteria": [{"id": "x", "label": "Fit"}],
        "cells": [["yes"]],
    }
    assert rules_of(one) == []
    assert "1 option compared on 1 criterion." in render_matrix(one)
    assert "2 options compared on 2 criteria." in render_matrix(sample())


def test_hostile_text_is_escaped() -> None:
    evil = "<script>x</script><img src=x>"
    data = sample(title=evil)
    data["options"][0].update(label=evil, note=evil)
    data["criteria"][0]["label"] = evil
    data["cells"][0][1] = evil
    out = render_matrix({**data, "recommended": "a"})
    assert "<script>" not in out and "<img" not in out and "style=" not in out


def test_copy_text_is_a_markdown_table() -> None:
    out = render_matrix(sample(recommended="a"))
    found = re.search(r'data-copy="([^"]*)"', out)
    assert found
    lines = html.unescape(found[1]).split("\n")
    assert lines[0] == "| Criterion | Alpha (recommended) | Beta |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| Cost | yes | no |"


def test_root_has_the_component_class_regions_and_a_text_alternative() -> None:
    out = render_matrix(sample())
    assert 'class="vb matrix vd-matrix"' in out
    assert 'role="region"' in out and 'tabindex="0"' in out
    assert 'class="vb-alt ' in out and "<th></th>" not in out
    assert '<div class="vb table"' not in out


def test_registered_help_and_fixtures() -> None:
    assert "matrix" in COMPONENTS
    text = files("varde_learn.docs").joinpath("help", "blocks.txt").read_text()
    assert type_text("matrix") in text
    for name in ("rich-matrix", "rich-matrix-stress"):
        doc = (FIXTURES / f"{name}.md").read_text()
        assert check(doc) == []
        body = render_page(doc, "t.md").body
        assert "vb-error" not in body and "<img" not in body
        assert "<script>alert" not in body and "style=" not in body
        assert "vd-matrix" in body


def test_stress_page_has_the_edge_cases() -> None:
    body = render_page((FIXTURES / "rich-matrix-stress.md").read_text(), "t.md").body
    assert "Twelve options" in body and body.count(', Recommended"') == 2


@pytest.mark.parametrize("name", ["rich-matrix", "rich-matrix-stress"])
def test_fixture_family_exists(name: str) -> None:
    assert (FIXTURES / f"{name}.md").exists()
