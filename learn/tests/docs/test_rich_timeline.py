"""The timeline component: statuses, current step, caps, escaping, registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.timeline import (
    copy_text,
    render_timeline,
    summary_text,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


def _item(n: int, status: str = "planned", **extra: str) -> dict[str, object]:
    return {"when": f"W{n}", "label": f"L{n}", "status": status, **extra}


def _tl(*items: dict[str, object], **props: object) -> dict[str, object]:
    return {"item": list(items), **props}


@pytest.mark.parametrize(
    ("status", "glyph", "word"),
    [("done", "✓", "Done"), ("active", "●", "Active"),
     ("planned", "○", "Planned"), ("blocked", "✕", "Blocked")],
)  # fmt: skip
def test_status_is_glyph_word_and_class(status: str, glyph: str, word: str) -> None:
    html = render_timeline(_tl(_item(1, status)))
    assert f"vd-timeline-item vd-timeline-{status}" in html
    assert f'aria-hidden="true">{glyph}</span>' in html
    assert f'<p class="vd-timeline-status">{word}</p>' in html


def test_exactly_one_active_item_is_current_or_none() -> None:
    two = render_timeline(_tl(_item(1, "done"), _item(2, "active"), _item(3, "active")))
    assert two.count('aria-current="step"') == 1
    assert 'vd-timeline-active" aria-current="step"' in two
    assert "aria-current" not in render_timeline(_tl(_item(1, "done")))


def test_order_is_preserved_and_copy_is_ordered_list() -> None:
    items = [_item(2, "done"), _item(1, "active"), _item(3)]
    html = render_timeline(_tl(*items))
    assert html.index("L2") < html.index("L1") < html.index("L3")
    assert copy_text(items) == "W2: L2 (done)\nW1: L1 (active)\nW3: L3 (planned)"
    assert 'data-copy="W2: L2 (done)' in html


def test_summary_is_plural_correct_and_skips_zero_counts() -> None:
    assert summary_text([_item(1, "done")]) == "1 milestone: 1 done"
    two = [_item(1, "done"), _item(2, "blocked")]
    assert summary_text(two) == "2 milestones: 1 done, 1 blocked"
    assert 'class="vb-alt vd-timeline-summary"' in render_timeline(_tl(*two))


def test_horizontal_has_a_labelled_focusable_region_and_vertical_does_not() -> None:
    horizontal = render_timeline(_tl(_item(1), orientation="horizontal", title="T"))
    assert 'role="region" aria-label="T, scrollable" tabindex="0"' in horizontal
    assert "vd-timeline-horizontal" in horizontal
    vertical = render_timeline(_tl(_item(1)))
    assert 'role="region"' not in vertical and "vd-timeline-vertical" in vertical
    assert '<section class="vb timeline vd-timeline' in vertical


def test_horizontal_is_capped_at_24_and_vertical_allows_100() -> None:
    items = [_item(n) for n in range(25)]
    assert check_props("timeline", _tl(*items, orientation="horizontal"), 1)
    assert check_props("timeline", _tl(*items[:24], orientation="horizontal"), 1) == []
    assert check_props("timeline", _tl(*[_item(n) for n in range(100)]), 1) == []
    html = render_timeline(_tl(*[_item(n) for n in range(100)]))
    assert html.count("<li ") == 100


def test_empty_when_and_other_bad_props_are_faults() -> None:
    assert check_props("timeline", _tl(_item(1)), 1) == []
    assert check_props("timeline", _tl(_item(1, owner="o", note="n")), 1) == []
    bads: tuple[dict[str, object], ...] = (
        {**_item(1), "when": ""},
        {**_item(1), "status": "late"},
        {"when": "a", "label": "b"},
        {**_item(1), "extra": 1},
        {**_item(1), "note": ""},
    )
    for bad in bads:
        assert check_props("timeline", _tl(bad), 1), bad
    assert check_props("timeline", _tl(), 1)
    assert check_props("timeline", _tl(_item(1), orientation="diagonal"), 1)
    assert check_props("timeline", _tl(_item(1), extra=1), 1)


def test_hostile_text_is_escaped() -> None:
    html = render_timeline(
        _tl(
            _item(
                1,
                "active",
                when="<b>w</b>",
                label="<script>x</script>",
                owner="<i>o</i>",
                note="<u>`<i>c</i>`",
            ),
            title="<img src=x>",
        )
    )
    assert "<script>" not in html and "<b>" not in html and "<i>" not in html
    assert "<img" not in html and "<u>" not in html
    assert "&lt;script&gt;" in html and "<code>&lt;i&gt;c&lt;/i&gt;</code>" in html
    assert "style=" not in html


def test_registered_and_renders_through_the_page() -> None:
    assert "timeline" in COMPONENTS
    doc = (FIXTURES / "rich-timeline.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert body.count("vd-timeline-item") >= 14
    assert "vb-error" not in body


def test_stress_fixture_validates_and_stays_escaped() -> None:
    doc = (FIXTURES / "rich-timeline-stress.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "<img" not in body and "<script>alert" not in body
    assert "style=" not in body and "vb-error" not in body
    assert body.count("vd-timeline-item") >= 230
