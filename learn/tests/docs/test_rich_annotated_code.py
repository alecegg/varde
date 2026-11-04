"""annotated-code: pins and notes agree and link both ways, ranges are checked,
quiet stretches fold, text is escaped, the layout rules ship in the stylesheet."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks_render.annotated_code import (
    CONTEXT,
    MIN_FOLD,
    Note,
    copy_text,
    hidden_runs,
    read_notes,
    render_annotated_code,
)
from varde_learn.docs.pages.render import render_page

PAGES = Path(__file__).parents[2] / "src" / "varde_learn" / "docs" / "pages"
FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
SOURCE = "".join(f"l{i} = {i}\n" for i in range(1, 41))


def props(notes: list[dict[str, Any]], **more: Any) -> dict[str, Any]:
    return {
        "filename": "f.py",
        "language": "python",
        "source": SOURCE,
        "notes": notes,
        **more,
    }


def rules_of(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("annotated-code", data, 1)]


def test_marker_count_equals_note_count_and_links_resolve() -> None:
    notes = [
        {"lines": "5-6", "note": "a"},
        {"lines": 20, "note": "b", "kind": "warn"},
        {"lines": 5, "note": "c", "kind": "change"},
    ]
    markup = render_annotated_code(props(notes))
    pins = re.findall(
        r'<a class="vd-annotated-pin[^"]*" id="(pin-[^"]+)" href="#([^"]+)"', markup
    )
    backs = re.findall(r'<a class="vd-annotated-back" href="#([^"]+)"', markup)
    items = re.findall(r'<li class="[^"]*" id="(note-[^"]+)"', markup)
    assert len(pins) == len(backs) == len(items) == len(notes)
    assert [href for _, href in pins] == items
    assert backs == [pin_id for pin_id, _ in pins]
    ids = re.findall(r' id="([^"]+)"', markup)
    assert len(ids) == len(set(ids))


def test_notes_are_numbered_by_start_line_with_ties_in_author_order() -> None:
    notes = read_notes(
        props(
            [
                {"lines": 9, "note": "late"},
                {"lines": 2, "note": "x"},
                {"lines": 2, "note": "y"},
            ]
        ),
        40,
    )
    assert [(n.number, n.start, n.text) for n in notes] == [
        (1, 2, "x"),
        (2, 2, "y"),
        (3, 9, "late"),
    ]


@pytest.mark.parametrize("lines", ["39-41", 41, "0", "3-2", "a", True, 2.5])
def test_bad_or_out_of_range_lines_fault(lines: object) -> None:
    assert rules_of(props([{"lines": lines, "note": "n"}])) in (["range"], ["type"])


def test_out_of_range_is_a_fault_and_the_renderer_clamps() -> None:
    data = props([{"lines": "39-99", "note": "n"}])
    assert rules_of(data) == ["range"]
    assert read_notes(data, 40)[0].end == 40
    assert 'data-from="39" data-to="40"' in render_annotated_code(data)


def test_limits_and_shape_faults() -> None:
    assert rules_of(props([{"lines": 1, "note": "n"}] * 41)) == ["limit", "limit"]
    assert "limit" in rules_of(props([{"lines": 1, "note": "n"}] * 7))
    assert rules_of(props([{"lines": 1, "note": "n", "kind": "bad"}])) == ["type"]
    assert rules_of(props([{"lines": 1}])) == ["missing-key"]
    assert rules_of(props([], collapse="no")) == ["type"]
    assert rules_of(props([])) == []
    assert rules_of(props([{"lines": 1, "note": "n"}] * 6)) == []


def test_hostile_text_is_escaped_and_backticks_become_code() -> None:
    hostile = '<script>alert(1)</script> "q" & <img src=x>'
    data = props([{"lines": 2, "label": hostile, "note": f"{hostile} `x<y`"}])
    data["filename"] = hostile
    markup = render_annotated_code(data)
    assert "<script>" not in markup and "<img" not in markup
    assert "style=" not in markup and "onclick" not in markup
    assert "<code>x&lt;y</code>" in markup


def test_quiet_stretches_fold_but_keep_context_around_notes() -> None:
    notes = read_notes(props([{"lines": "20-21", "note": "n"}]), 40)
    runs = hidden_runs(notes, 40)
    assert runs == [(1, 20 - CONTEXT - 1), (21 + CONTEXT + 1, 40)]
    assert all(b - a + 1 >= MIN_FOLD for a, b in runs)
    markup = render_annotated_code(props([{"lines": "20-21", "note": "n"}]))
    assert "16 lines hidden (lines 1-16)" in markup
    assert markup.count('<details class="vd-annotated-fold">') == 2
    for line in range(1, 41):  # folding hides lines, it never drops them
        assert f'data-line="{line}"' in markup


def test_short_gaps_and_collapse_false_do_not_fold() -> None:
    near = [{"lines": 5, "note": "a"}, {"lines": 12, "note": "b"}]
    assert hidden_runs(read_notes(props(near), 40), 40)[0] != (6, 11)
    off = render_annotated_code(props([{"lines": 20, "note": "n"}], collapse=False))
    assert "<details" not in off


def test_empty_notes_render_the_plain_panel() -> None:
    markup = render_annotated_code(props([]))
    assert "vd-annotated-notes" not in markup and "vd-annotated-pin" not in markup
    assert 'class="vb annotated-code ' in markup


def test_root_names_the_component_and_data_copy_is_source_then_notes() -> None:
    markup = render_annotated_code(props([{"lines": 2, "label": "L", "note": "n"}]))
    assert markup.startswith('<div class="vb annotated-code vd-annotated-code ')
    copy = re.search(r'^<div[^>]*data-copy="([^"]*)"', markup)
    assert copy and copy[1].startswith("l1 = 1\nl2 = 2")
    assert copy[1].endswith("1. line 2: L: n")
    note = Note(1, 2, 3, "", "t", "info")
    assert copy_text("a\n", [note]) == "a\n\n1. lines 2-3: t"


def test_kinds_show_a_word_and_glyph_not_only_colour() -> None:
    notes = [
        {"lines": i, "note": "n", "kind": k}
        for i, k in enumerate(["info", "warn", "change"], 1)
    ]
    markup = render_annotated_code(props(notes))
    for word in ("Info", "Warning", "Change"):
        assert f"</span> {word} " in markup
    assert 'aria-label="Note 2, warning, line 2"' in markup


def test_large_source_and_long_line() -> None:
    source = "\n".join(f"{i} " + "z" * 400 for i in range(600)) + "\n"
    data = props([{"lines": 300, "note": "mid"}, {"lines": 600, "note": "end"}])
    data["source"] = source
    markup = render_annotated_code(data)
    assert markup.count('data-line="') == 600
    assert markup.count("<details") == 2
    assert 'class="vd-code-line vd-annotated-pinned" data-line="600"' in markup


def test_fixtures_render_as_components_without_error_cards() -> None:
    for name, count in (("rich-annotated-code", 2), ("rich-annotated-code-stress", 3)):
        body = render_page((FIXTURES / f"{name}.md").read_text(), "t.md").body
        assert body.count(" vd-annotated-code ") == count
        assert "vb-error" not in body


def test_stylesheet_has_margin_layout_print_and_forced_colours_rules() -> None:
    css = (PAGES / "static" / "css" / "48-annotated.css").read_text()
    assert "@container vd-doc (min-width: 44rem)" in css
    assert css.index("@container vd-doc") < css.index(
        "grid-template-columns: minmax(0, 1fr) 18rem"
    )
    assert "@media (forced-colors: active)" in css and "@media print" in css
    assert "min-block-size: 44px" in css and "style=" not in css


def test_script_has_no_inline_handlers_and_handles_print() -> None:
    js = (PAGES / "static" / "annotated.js").read_text()
    assert "beforeprint" in js and "innerHTML" not in js


def test_pins_reserve_room_without_line_numbers_too() -> None:
    css = (PAGES / "static" / "css" / "48-annotated.css").read_text()
    assert re.search(
        r"\.vd-annotated-code \.vd-code-nonum \.vd-code-line \{[^}]*"
        r"padding-inline-start: calc\([^}]*var\(--vd-pin-cols\)",
        css,
    )
