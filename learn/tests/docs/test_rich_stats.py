"""The stats component: tones, flat, item counts, escaping, registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.stats import (
    card_name,
    copy_text,
    render_stats,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


def _stats(*items: dict[str, object]) -> dict[str, object]:
    return {"item": list(items)}


def _pair(first: dict[str, object]) -> dict[str, object]:
    return _stats({"label": "L", "value": 1, **first}, {"label": "M", "value": 2})


@pytest.mark.parametrize(
    ("direction", "good", "tone", "word"),
    [
        ("up", "up", "success", "up"),
        ("up", "down", "risk", "up"),
        ("down", "down", "success", "down"),
        ("down", "up", "risk", "down"),
        ("flat", "up", "neutral", "flat"),
    ],
)
def test_tone_comes_from_direction_against_good(
    direction: str, good: str, tone: str, word: str
) -> None:
    html = render_stats(_pair({"delta": "5%", "direction": direction, "good": good}))
    assert f"vd-stats-card vd-stats-{tone}" in html
    assert f'<span class="vd-stats-word">{word}</span>' in html
    assert 'class="vd-stats-glyph" aria-hidden="true"' in html


def test_delta_without_good_is_neutral_and_sign_gives_direction() -> None:
    html = render_stats(_pair({"delta": "-8%"}))
    assert "vd-stats-card vd-stats-neutral" in html
    assert 'down</span></span> <span class="vd-stats-number">8%</span>' in html


def test_explicit_tone_wins() -> None:
    html = render_stats(
        _pair({"delta": "1", "direction": "up", "good": "up", "tone": "warning"})
    )
    assert "vd-stats-card vd-stats-warning" in html


def test_missing_delta_renders_no_change() -> None:
    html = render_stats(_pair({}))
    assert "vd-stats-delta" not in html
    assert 'aria-label="L: 1"' in html


def test_card_name_and_copy_text_carry_the_word() -> None:
    item: dict[str, object] = {"label": "Req", "value": 1204331, "delta": "+12%"}
    assert card_name(item) == "Req: 1,204,331, up 12%"
    assert copy_text([item, {"label": "B", "value": "x"}]) == (
        "Req: 1,204,331 (up 12%)\nB: x"
    )
    assert 'data-copy="Req: 1,204,331 (up 12%)\nB: x"' in render_stats(
        _stats(item, {"label": "B", "value": "x"})
    )


def test_numbers_group_thousands_and_decimals_fix_places() -> None:
    html = render_stats(_pair({"value": 1234.5, "decimals": 2}))
    assert ">1,234.50<" in html
    assert ">1,234,567<" in render_stats(_pair({"value": 1234567}))


@pytest.mark.parametrize("count", [2, 6])
def test_two_and_six_items_are_valid(count: int) -> None:
    items = [{"label": f"L{n}", "value": n} for n in range(count)]
    assert check_props("stats", {"item": items}, 1) == []
    html = render_stats({"item": items})
    assert html.count('role="group"') == count
    assert f"vd-stats-n{count}" in html and f"{count} stats" in html


@pytest.mark.parametrize("count", [1, 7])
def test_other_item_counts_are_a_fault(count: int) -> None:
    items = [{"label": f"L{n}", "value": n} for n in range(count)]
    assert check_props("stats", {"item": items}, 1)


def test_forty_character_values_stay_whole_text() -> None:
    value = "1,234,567 requests per second sustained"
    assert len(value) >= 38
    html = render_stats(_pair({"value": value}))
    assert f">{value}<" in html


def test_hostile_text_is_escaped() -> None:
    html = render_stats(
        _pair(
            {
                "label": "<b>x</b>",
                "value": "<script>x</script>",
                "delta": "<i>",
                "direction": "up",
                "note": "<u>`<i>c</i>`",
            }
        )
    )
    assert "<script>" not in html and "<b>x</b>" not in html and "<i>" not in html
    assert "&lt;script&gt;" in html and "<code>&lt;i&gt;c&lt;/i&gt;</code>" in html
    assert "style=" not in html


def test_spec_rejects_bad_props() -> None:
    ok = [{"label": "a", "value": 1}, {"label": "b", "value": 2}]
    assert check_props("stats", {"item": ok, "covers": ["x"]}, 1) == []
    for bad in (
        {"label": "a"},
        {"label": "a", "value": 1, "direction": "sideways"},
        {"label": "a", "value": 1, "good": "flat"},
        {"label": "a", "value": 1, "tone": "loud"},
        {"label": "a", "value": 1, "delta": "12%"},
        {"label": "a", "value": 1, "decimals": 9},
        {"label": "a", "value": True},
        {"label": "a", "value": 1, "extra": 1},
    ):
        assert check_props("stats", {"item": [bad, ok[1]]}, 1), bad
    assert check_props("stats", {"item": ok, "extra": 1}, 1)


def test_registered_and_renders_through_the_page() -> None:
    assert "stats" in COMPONENTS
    doc = (FIXTURES / "rich-stats.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert body.count("vd-stats-card") >= 8
    assert "vb-error" not in body


def test_stress_fixture_validates_and_stays_escaped() -> None:
    doc = (FIXTURES / "rich-stats-stress.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "<img" not in body and "<script>alert" not in body
    assert "style=" not in body and "vb-error" not in body
