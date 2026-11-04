"""Ranking redesign: stylesheet rules, markup, and the badge/live text in a browser."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.serve import PageServer

from .test_inputs_ordered import _open, shared_page, site  # noqa: F401

PAGES = Path(str(files("varde_learn.docs.pages")))
CSS = re.sub(
    r"/\*.*?\*/",
    "",
    (PAGES / "static" / "css" / "24-ranking.css").read_text(),
    flags=re.DOTALL,
)
DECLARATION = re.compile(r"([a-z-]+)\s*:\s*([^;{}]+);")
LENGTH = re.compile(r"-?\d*\.?\d+(?:px|rem|em|vw|vh|ch)\b")
PHYSICAL = re.compile(
    r"\b(?:margin|padding|border)-(?:left|right|top|bottom)\b"
    r"|(?<![\w-])(?:left|right|top|bottom|width|height|min-width|min-height)\s*:"
)


def _render(items: list[object]) -> str:
    return COMPONENTS["ranking"].render({"question": "Q", "items": items}, "w")


def test_li_is_not_flex_and_numbers_are_a_counter_badge() -> None:
    row = re.search(r"\.ranking-row \{([^}]*)\}", CSS)
    assert row and "display: list-item" in row.group(1) and "flex" not in row.group(1)
    assert "counter-reset: rank" in CSS and "counter-increment: rank" in CSS
    assert re.search(r"\.ranking-line::before \{[^}]*content: counter\(rank\)", CSS)


def test_spacing_sizes_and_logical_properties_come_from_tokens() -> None:
    for prop, value in DECLARATION.findall(CSS):
        if re.match(r"^(margin|padding|gap)(-|$)", prop) or prop in (
            "min-block-size",
            "min-inline-size",
        ):
            bare = re.sub(r"var\(--vd-[\w-]+\)", "", value)
            assert not LENGTH.search(bare), (prop, value)
    assert PHYSICAL.findall(CSS) == []


def test_focus_ring_is_not_overridden_and_nothing_hides_overflow() -> None:
    assert not re.search(r"outline|:focus", CSS)
    assert not re.search(r"overflow(-[xy])?:\s*(hidden|auto|scroll|clip)", CSS)


def test_drag_is_pointer_fine_only_and_touch_scroll_survives() -> None:
    assert "@media (pointer: fine)" in CSS
    assert "touch-action: pan-y" in CSS
    js = (PAGES / "static" / "inputs_ordered.js").read_text()
    assert "(pointer: fine)" in js


def test_elevation_drop_line_and_forced_colors_are_styled() -> None:
    for needle in (".dragging", ".over-before", ".over-after", "forced-colors: active"):
        assert needle in CSS, needle


def test_markup_has_hidden_grip_and_logical_buttons() -> None:
    out = _render(["a", "b"])
    assert out.count('class="ranking-grip" aria-hidden="true"') == 2
    # up and down arrows, never left and right
    assert out.count("&#8593;") == 2 and out.count("&#8595;") == 2
    assert "style=" not in out and "<script" not in out


@pytest.mark.slow
def test_browser_badges_show_rank_and_live_text_changes(
    shared_page: Any,  # noqa: F811
    site: tuple[PageServer, Path],  # noqa: F811
) -> None:
    server, _doc = site
    page = shared_page
    _open(page, server)
    page.wait_for_selector(".ranking[data-hydrated]")
    badges = page.eval_on_selector_all(
        ".ranking-line",
        "ls => ls.map(l => getComputedStyle(l, '::before').content)",
    )
    assert badges == ["counter(rank)"] * 3  # numbered by the CSS counter
    seen = []
    for label in ("Move a down", "Move a down", "Move a up"):
        page.locator(f"[aria-label='{label}']").click()
        page.wait_for_function(
            "t => { const l = document.querySelector('.ranking-live');"
            " return l.textContent && l.textContent !== t; }",
            arg=seen[-1] if seen else "",
        )
        seen.append(page.locator(".ranking-live").text_content())
    assert seen == [f"a is at position {n} of 3." for n in (2, 3, 2)]


def test_row_wraps_and_label_keeps_min_content_room() -> None:
    line = re.search(r"\.ranking-line \{([^}]*)\}", CSS)
    assert line and "flex-wrap: wrap" in line.group(1)
    text = re.search(r"\.ranking-text \{([^}]*)\}", CSS)
    assert text
    assert "flex: 1 1 calc(" in text.group(1)  # basis wide enough to push buttons down
    # anywhere keeps min-content tiny so a long word cannot widen the fieldset and page
    assert "overflow-wrap: anywhere" in text.group(1)
    assert re.search(r"\.ranking-group \{[^}]*min-inline-size: 0", CSS)


def test_card_does_not_clip_focus_rings_and_print_resets_clipping() -> None:
    assert re.search(r"\.ranking \.vb-card \{[^}]*overflow: visible", CSS)
    print_block = CSS[CSS.index("@media print") :]
    assert ".ranking .vb-card" in print_block and "overflow: visible" in print_block
    assert CSS.rstrip().endswith("}") and CSS.rindex("@media print") > CSS.rindex(
        "@media (forced-colors"
    )
