"""Source-level regressions for the final visual review fixes."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).parents[2] / "src/varde_learn/docs/pages/static"


def css(name: str) -> str:
    return (STATIC / "css" / name).read_text()


def rule(text: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text)
    assert match, selector
    return match.group(1)


def test_diagram_and_flow_fit_the_whole_graph_on_first_paint() -> None:
    for name in ("diagram.js", "flow.js"):
        js = (STATIC / name).read_text()
        assert "const MIN_FIT = 0.25;" in js
        assert "TARGET" not in js
        assert "minUnit" not in js
        assert "refit();" in js


def test_menu_button_is_a_44px_bordered_target_with_text_colour() -> None:
    body = rule(css("30-menu.css"), ".menu-btn")
    assert "var(--vd-control-height)" in body
    assert "min-inline-size: 44px" in body and "min-block-size: 44px" in body
    assert "border: 1px solid var(--vd-border-interactive)" in body
    assert "color: var(--vd-text)" in body
    assert "neutral-muted" not in body


def test_screen_flow_frame_shrinks_to_its_content() -> None:
    assert "inline-size: fit-content" in rule(css("58-screen-flow.css"), ".vd-sf-view")


def test_scroll_regions_show_an_edge_cue_with_a_solid_bar() -> None:
    for name, selector in (
        ("40-table.css", ".vb-scroll"),
        ("50-blocks.css", ".vb-card"),
    ):
        body = rule(css(name), selector)
        assert "scroll 0 0" in body and "scroll 100% 0" in body
        assert "var(--vd-text-secondary) 0 3px" in body  # a solid bar, not colour alone


def test_wrapped_table_text_keeps_a_readable_width_on_phones_only() -> None:
    text = css("40-table.css")
    selector = ".vb-table:not(.vb-table-stack) td:not(.vb-num)"
    assert (
        "@media screen and (max-width: 40rem) { "
        + selector
        + " { min-inline-size: 6rem; } }"
        in text
    )
    assert text.rstrip().endswith("}") and text.rfind("@media print") > text.rfind(
        "min-inline-size: 6rem"
    )


def test_card_background_is_cleared_for_print() -> None:
    assert (
        ".vb-card { background: none; }"
        in css("50-blocks.css").split("@media print")[-1]
    )
