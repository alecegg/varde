"""diff: rows agree with difflib, long unchanged runs fold, notes link, text is escaped,
the unified diff in data-copy round-trips, the layout rules ship in the stylesheet."""

from __future__ import annotations

import difflib
import html
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props, type_text
from varde_learn.docs.pages.blocks.diff_rows import (
    MAX_ROWS,
    diff_rows,
    patch_rows,
    text_lines,
)
from varde_learn.docs.pages.blocks_render.diff import render_diff

PAGES = Path(str(files("varde_learn.docs.pages")))
FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
BEFORE = "".join(f"line {i}\n" for i in range(1, 31))
AFTER = BEFORE.replace("line 15\n", "line fifteen\n")


def copy_of(markup: str) -> str:
    found = re.search(r'data-copy="([^"]*)"', markup)
    assert found
    return html.unescape(found[1])


def without_copy(markup: str) -> str:
    return re.sub(r' data-copy="[^"]*"', "", markup)


def rules_of(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("diff", data, 1)]


def test_rows_follow_difflib_and_carry_both_line_numbers() -> None:
    rows = diff_rows("a\nb\nc\n", "a\nB\nc\nd\n")
    assert [(r.kind, r.old, r.new, r.text) for r in rows] == [
        ("same", 1, 1, "a"),
        ("del", 2, None, "b"),
        ("add", None, 2, "B"),
        ("same", 3, 3, "c"),
        ("add", None, 4, "d"),
    ]
    assert diff_rows("a\nb\n", "a\nB\n") == diff_rows("a\nb\n", "a\nB\n")


def test_identical_and_empty_sides() -> None:
    same = render_diff({"before": "a\nb\n", "after": "a\nb\n"})
    assert "No changes" in same and "vd-diff-add" not in same
    added = render_diff({"filename": "n.txt", "before": "", "after": "x\ny\n"})
    assert "added</span>" in added and "@@ -0,0 +1,2 @@" in added
    removed = render_diff({"filename": "n.txt", "before": "x\ny\n", "after": ""})
    assert "removed</span>" in removed and "@@ -1,2 +0,0 @@" in removed
    assert copy_of(added).startswith("--- a/n.txt\n+++ b/n.txt\n@@ -0,0 +1,2 @@")


def test_trailing_newline_and_crlf_do_not_change_the_rows() -> None:
    assert diff_rows("a\nb", "a\nb\n") == diff_rows("a\nb\n", "a\nb\n")
    assert diff_rows("a\r\nb\r\n", "a\nB\n") == diff_rows("a\nb\n", "a\nB\n")
    assert text_lines("") == [] and text_lines("\n") == [""]


def test_markers_are_text_not_colour() -> None:
    markup = render_diff({"before": "a\nb\n", "after": "a\nc\n"})
    assert (
        '<span aria-hidden="true">-</span><span class="vd-diff-sr">removed</span>'
        in markup
    )
    assert (
        '<span aria-hidden="true">+</span><span class="vd-diff-sr">added</span>'
        in markup
    )
    assert "+1 added, -1 removed" in markup and "modified" in markup


def test_data_copy_is_the_unified_diff_and_round_trips() -> None:
    markup = render_diff({"filename": "f.txt", "before": BEFORE, "after": AFTER})
    text = copy_of(markup)
    expected = list(
        difflib.unified_diff(
            BEFORE.splitlines(), AFTER.splitlines(), "", "", lineterm=""
        )
    )[2:]
    assert text.splitlines() == ["--- a/f.txt", "+++ b/f.txt", *expected]
    parsed = patch_rows(text)
    assert parsed is not None
    rows, _, _ = parsed
    olds = [r.text for r in rows if r.old]
    news = [r.text for r in rows if r.new]
    assert "line 15" in olds and "line fifteen" in news


def test_patch_input_renders_like_before_and_after() -> None:
    patch = "\n".join(
        difflib.unified_diff(
            BEFORE.splitlines(),
            AFTER.splitlines(),
            "a/f.py",
            "b/f.py",
            lineterm="",
            n=10**6,
        )
    )
    from_texts = render_diff(
        {"filename": "f.py", "language": "python", "before": BEFORE, "after": AFTER}
    )
    from_patch = render_diff({"language": "python", "patch": patch})
    assert without_copy(from_texts) == without_copy(from_patch)
    assert copy_of(from_patch) == patch


def test_patch_gaps_and_renames() -> None:
    hunks = "@@ -3,2 +3,2 @@\n a\n-b\n+B\n@@ -40,1 +40,1 @@\n z\n"
    patch = "--- a/old.py\n+++ b/new.py\n" + hunks
    markup = render_diff({"patch": patch})
    assert "2 unchanged lines not in the patch" in markup
    assert "35 unchanged lines not in the patch" in markup
    assert "renamed" in markup and "old.py" in markup and "new.py" in markup


def test_long_unchanged_runs_fold_to_three_lines_at_each_edge() -> None:
    markup = render_diff({"before": BEFORE, "after": AFTER})
    assert markup.count('<details class="vd-diff-fold">') == 2
    assert "11 unchanged lines hidden (lines 1-11)" in markup
    assert "12 unchanged lines hidden (lines 19-30)" in markup
    for number in range(1, 31):  # folding hides rows, it never drops them
        assert f'<td class="vd-diff-text">line {number}</td>' in markup or number == 15
    short = render_diff(
        {"before": "a\nb\nc\nd\ne\nf\ng\n", "after": "A\nb\nc\nd\ne\nf\ng\n"}
    )
    assert "<details" not in short


def test_noted_lines_stay_visible_and_pins_match_notes() -> None:
    notes = [
        {"side": "before", "lines": "2-3", "note": "keep"},
        {"side": "after", "lines": 28, "note": "tail"},
    ]
    markup = render_diff({"before": BEFORE, "after": AFTER, "notes": notes})
    assert markup.count("<details") == 3
    assert "8 unchanged lines hidden (lines 4-11)" in markup
    pins = re.findall(r'href="#(note-[^"]+)" aria-label="Note (\d), (\w+) line', markup)
    items = re.findall(r'<li class="vd-diff-note" id="(note-[^"]+)"', markup)
    assert [p[0] for p in pins] == items and len(items) == 2
    ids = re.findall(r' id="([^"]+)"', markup)
    assert len(ids) == len(set(ids))


def test_split_mode_holds_both_tables_unified_holds_one() -> None:
    split = render_diff({"before": BEFORE, "after": AFTER, "mode": "split"})
    assert "vd-diff-unified" in split and "vd-diff-sbs" in split
    assert split.count('tabindex="0"') == 2 and split.count('role="region"') == 2
    one = render_diff({"before": BEFORE, "after": AFTER, "mode": "unified"})
    assert "vd-diff-sbs" not in one and 'class="vb diff ' in one


def test_split_pairs_deletions_with_additions() -> None:
    markup = render_diff({"before": "a\nb\n", "after": "a\nB\nC\n", "mode": "split"})
    sbs = markup[markup.index("vd-diff-sbs") :]
    assert sbs.count('<tr class="vd-diff-row">') == 3
    assert (
        sbs.count("vd-diff-empty") == 3
    )  # the unmatched addition has an empty left side


def test_hostile_text_is_escaped() -> None:
    hostile = '<script>alert(1)</script> "q" & <img src=x>'
    markup = render_diff(
        {
            "filename": hostile,
            "language": 'py"><b>',
            "before": hostile,
            "after": hostile + "!",
            "notes": [{"side": "after", "lines": 1, "note": f"{hostile} `x<y`"}],
        }
    )
    assert "<script>" not in markup and "<img" not in markup and "<b>" not in markup
    assert "style=" not in markup and "onclick" not in markup
    assert "<code>x&lt;y</code>" in markup


def test_input_cap_adds_a_row_and_a_fault() -> None:
    big = "".join(f"x{i}\n" for i in range(MAX_ROWS + 20))
    data: dict[str, object] = {"before": "", "after": big}
    markup = render_diff(data)
    assert "20 more lines not shown" in markup
    assert rules_of(data) == ["limit"]


@pytest.mark.parametrize(
    ("data", "rules"),
    [
        ({}, ["input"]),
        ({"before": "a"}, ["input"]),
        ({"patch": "x", "before": "a", "after": "b"}, ["input", "type"]),
        ({"patch": "no hunk here"}, ["type"]),
        ({"before": "a", "after": "b", "mode": "wide"}, ["type"]),
        ({"before": "a", "after": "b", "extra": 1}, ["unknown-key"]),
        ({"before": 1, "after": "b"}, ["type"]),
        (
            {
                "before": "a",
                "after": "b",
                "notes": [{"side": "after", "lines": 5, "note": "n"}],
            },
            ["range"],
        ),
        (
            {
                "before": "a",
                "after": "b",
                "notes": [{"side": "left", "lines": 1, "note": "n"}],
            },
            ["type"],
        ),
        (
            {"before": "a", "after": "b", "notes": [{"side": "after", "lines": 1}]},
            ["missing-key"],
        ),
        ({"before": "", "after": ""}, []),
        (
            {
                "before": "a",
                "after": "b",
                "notes": [{"side": "after", "lines": "1", "note": "n"}],
            },
            [],
        ),
    ],
)
def test_validation(data: dict[str, Any], rules: list[str]) -> None:
    assert rules_of(data) == rules


def test_stylesheet_ships_the_layout_rules() -> None:
    css = (PAGES / "static" / "css" / "52-diff.css").read_text()
    for needle in (
        "@container vd-doc (min-width: 44rem)",
        "forced-colors",
        "@media print",
        "::details-content",
        "min-block-size: 44px",
        "outline-offset: -",
    ):
        assert needle in css
    assert "style=" not in css and not re.search(r"#[0-9a-fA-F]{3,8}\b", css)


def test_help_text_and_fixtures() -> None:
    text = files("varde_learn.docs").joinpath("help", "blocks.txt").read_text()
    assert type_text("diff") in text
    for name in ("rich-diff.md", "rich-diff-stress.md"):
        assert check((FIXTURES / name).read_text(), None) == []
    page = (FIXTURES / "rich-diff-stress.md").read_text()
    assert page.count("= diff(") >= 5
