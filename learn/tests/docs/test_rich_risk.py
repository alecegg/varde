"""The risks component: severity table, unique ids, counts, caps, escaping."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.risk import (
    copy_text,
    render_risk,
    severity_of,
    summary_text,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


def _risk(
    n: int, likelihood: str = "low", impact: str = "low", **extra: str
) -> dict[str, object]:
    return {
        "id": f"R{n}",
        "label": f"L{n}",
        "likelihood": likelihood,
        "impact": impact,
        **extra,
    }


def _data(*items: dict[str, object], **props: object) -> dict[str, object]:
    return {"item": list(items), **props}


@pytest.mark.parametrize(
    ("likelihood", "impact", "expected"),
    [
        ("low", "low", "low"), ("low", "medium", "low"),
        ("medium", "low", "low"), ("low", "high", "medium"),
        ("high", "low", "medium"), ("medium", "medium", "medium"),
        ("medium", "high", "high"), ("high", "medium", "high"),
        ("high", "high", "critical"),
    ],
)  # fmt: skip
def test_severity_table_covers_all_nine_cells(
    likelihood: str, impact: str, expected: str
) -> None:
    assert severity_of(likelihood, impact) == expected


def test_each_cell_has_its_severity_class_and_a_glyph() -> None:
    html = render_risk(_data(_risk(1)))
    for sev in ("low", "medium", "high", "critical"):
        assert f"vd-risk-cell-{sev}" in html
    assert html.count('<div class="vd-risk-cell ') == 9


def test_aria_label_counts_equal_items() -> None:
    items = [_risk(1, "high", "high"), _risk(2, "high", "high"), _risk(3)]
    assert summary_text(items) == "3 risks: 2 critical, 1 low"
    html = render_risk(_data(*items))
    assert 'role="img" aria-label="3 risks: 2 critical, 1 low"' in html
    label = re.search(r'role="img" aria-label="(\d+) risks', html)
    assert label and int(label.group(1)) == html.count("<dt>")
    assert summary_text([_risk(1)]) == "1 risk: 1 low"
    assert 'class="vb-alt vd-risk-summary"' in html


def test_list_has_every_field_and_severity_is_glyph_plus_word() -> None:
    html = render_risk(
        _data(_risk(1, "high", "high", mitigation="Do it.", owner="Ops"))
    )
    assert '<dt><span class="vd-risk-id">R1</span>' in html
    assert "Mitigation</span> Do it." in html and "Owner</span> Ops" in html
    assert 'aria-hidden="true">◆</span> <span class="vd-risk-sevword">Critical' in html
    assert '<section class="vb risks vd-risk"' in html


def test_empty_cell_renders_without_chips() -> None:
    html = render_risk(_data(_risk(1, "high", "high")))
    assert html.count("vd-risk-empty") == 8
    assert html.count('<span class="vd-risk-chip">') == 1


def test_thirty_in_one_cell_show_four_chips_and_a_more_marker() -> None:
    items = [_risk(n, "high", "high") for n in range(30)]
    html = render_risk(_data(*items))
    assert html.count('<span class="vd-risk-chip">') == 4
    assert '<span class="vd-risk-more">+26</span>' in html
    assert html.count("<dt>") == 30
    exact = render_risk(_data(*items[:4]))
    assert "vd-risk-more" not in exact


def test_duplicate_id_and_other_bad_props_are_faults() -> None:
    assert check_props("risks", _data(_risk(1)), 1) == []
    ok = _risk(1, mitigation="m", owner="o")
    assert check_props("risks", _data(ok), 1) == []
    dup = check_props("risks", _data(_risk(1), {**_risk(2), "id": "R1"}), 1)
    assert [f.rule for f in dup] == ["duplicate-id"]
    bads: tuple[dict[str, object], ...] = (
        {**_risk(1), "likelihood": "extreme"},
        {**_risk(1), "impact": "none"},
        {**_risk(1), "id": ""},
        {"id": "a", "label": "b", "likelihood": "low"},
        {**_risk(1), "extra": 1},
        {**_risk(1), "mitigation": ""},
    )
    for bad in bads:
        assert check_props("risks", _data(bad), 1), bad
    assert check_props("risks", _data(), 1)
    assert check_props("risks", _data(_risk(1), extra=1), 1)


def test_item_cap_is_200() -> None:
    items = [_risk(n) for n in range(201)]
    assert check_props("risks", _data(*items), 1)
    assert check_props("risks", _data(*items[:200]), 1) == []


def test_copy_text_is_the_list() -> None:
    items = [_risk(1, "high", "low", mitigation="m", owner="o"), _risk(2)]
    assert copy_text(items) == (
        "R1: L1 (likelihood high, impact low, severity medium); "
        "mitigation: m; owner: o\n"
        "R2: L2 (likelihood low, impact low, severity low)"
    )
    assert 'data-copy="R1: L1' in render_risk(_data(*items))


def test_hostile_text_is_escaped() -> None:
    html = render_risk(
        _data(
            _risk(
                1,
                "high",
                "high",
                id="<b>x</b>",
                label="<script>x</script>",
                mitigation="<u>m</u>",
                owner="<i>o</i>",
            ),
            title="<img src=x>",
        )
    )
    for raw in ("<script>", "<b>", "<u>", "<i>", "<img"):
        assert raw not in html
    assert "&lt;script&gt;" in html and "style=" not in html


def test_registered_and_renders_through_the_page() -> None:
    assert "risks" in COMPONENTS
    doc = (FIXTURES / "rich-risk.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert body.count("<dt>") == 15
    assert "vb-error" not in body


def test_stress_fixture_validates_and_stays_escaped() -> None:
    doc = (FIXTURES / "rich-risk-stress.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "<img" not in body and "<script>alert" not in body
    assert "style=" not in body and "vb-error" not in body
    assert body.count("<dt>") == 235
