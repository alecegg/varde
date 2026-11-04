"""The sequence component: layout, faults, text alternative, escaping, hooks."""

from __future__ import annotations

import itertools
import math
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.sequence import render_sequence, step_text
from varde_learn.docs.pages.blocks_render.sequence_layout import (
    CHAR_W,
    layout,
    place_actors,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
STATIC = Path(str(files("varde_learn.docs.pages").joinpath("static")))


def actors(count: int = 3) -> list[dict[str, Any]]:
    return [{"id": f"a{i}", "label": f"Actor {i}"} for i in range(count)]


def sample(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "desc": "d",
        "actors": actors(),
        "steps": [
            {"from": "a0", "to": "a1", "text": "hello"},
            {"from": "a1", "to": "a1", "text": "think"},
            {"from": "a1", "to": "a0", "text": "back", "kind": "return"},
        ],
    }
    return {**data, **extra}


def rules_of(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("sequence", data, 1)]


def test_layout_is_deterministic_and_byte_identical() -> None:
    data = sample()
    assert layout(data["actors"], data["steps"]) == layout(
        data["actors"], data["steps"]
    )
    assert render_sequence(data) == render_sequence(sample())


def test_layout_numbers_are_finite_ints_and_rows_do_not_overlap() -> None:
    geo = layout(actors(5), [{"from": "a0", "to": "a4", "text": "w " * 80}] * 6)
    numbers = [geo.width, geo.height]
    for row in geo.rows:
        numbers += [row.x1, row.x2, row.y, row.h, row.arrow_y, row.text_x]
    assert all(isinstance(n, int) and math.isfinite(n) for n in numbers)
    for upper, lower in itertools.pairwise(geo.rows):
        assert upper.y + upper.h <= lower.y


def test_actor_boxes_never_overlap_and_long_labels_truncate_with_a_title() -> None:
    labels = ["Averyveryverylonglabelwithnobreaks" * 3, "Two words here", "x " * 40]
    placed = place_actors([{"id": f"i{n}", "label": t} for n, t in enumerate(labels)])
    for left, right in itertools.pairwise(placed):
        assert left.box_x + left.box_w < right.box_x
    assert all(len(a.lines) <= 2 for a in placed)
    assert placed[0].truncated and placed[2].truncated and not placed[1].truncated
    html = render_sequence(
        sample(actors=[{"id": "a0", "label": labels[0]}, *actors(3)[1:]])
    )
    assert f"<title>{labels[0]}</title>" in html


def test_self_call_is_a_loop_and_kinds_use_distinct_shapes() -> None:
    html = render_sequence(sample())
    assert html.count("vd-sequence-row vd-sequence-call") == 2
    assert "vd-sequence-dashed" in html  # the return
    geo = layout(sample()["actors"], sample()["steps"])
    assert [r.self_call for r in geo.rows] == [False, True, False]
    shapes = render_sequence(
        sample(
            steps=[
                {"from": "a0", "to": "a1", "text": "c"},
                {"from": "a0", "to": "a1", "text": "a", "kind": "async"},
                {"from": "a0", "to": "a1", "text": "n", "kind": "note"},
            ]
        )
    )
    assert "<polygon" in shapes and "vd-sequence-head-open" in shapes
    assert "vd-sequence-note-box" in shapes


def test_groups_become_labelled_frames_over_their_rows() -> None:
    steps = [
        {"from": "a0", "to": "a1", "text": "x"},
        {"from": "a1", "to": "a0", "text": "y", "group": "alt: cache"},
        {"from": "a0", "to": "a1", "text": "z", "group": "alt: cache"},
        {"from": "a1", "to": "a0", "text": "w", "group": "loop"},
        {"from": "a0", "to": "a1", "text": "v"},
    ]
    geo = layout(actors(2), steps)
    assert [f.label for f in geo.frames] == ["alt: cache", "loop"]
    first = geo.frames[0]
    assert (
        first.y < geo.rows[1].y and geo.rows[2].y + geo.rows[2].h <= first.y + first.h
    )
    assert geo.rows[3].y >= first.y + first.h
    html = render_sequence(sample(steps=steps))
    assert html.count('class="vd-sequence-frame"') == 2
    assert ">alt: cache</text>" in html


def test_twelve_actors_widen_the_drawing_without_overlap() -> None:
    wide = layout(actors(12), [{"from": "a0", "to": "a11", "text": "far"}])
    narrow = layout(actors(3), [{"from": "a0", "to": "a2", "text": "near"}])
    assert wide.width > narrow.width * 3
    xs = [a.x for a in wide.actors]
    assert xs == sorted(xs) and len(set(xs)) == 12


def test_two_hundred_steps_render_and_validate() -> None:
    steps = [{"from": "a0", "to": "a1", "text": f"s{n}"} for n in range(200)]
    data = sample(steps=steps)
    assert rules_of(data) == []
    html = render_sequence(data)
    assert html.count("<li ") == 200 and html.count('class="vd-sequence-row') == 200
    assert "NaN" not in html and "None" not in html


def test_ordered_text_alternative_equals_the_steps() -> None:
    data = sample(
        steps=[
            {"from": "a0", "to": "a1", "text": "one"},
            {"from": "a1", "to": "a0", "text": "two", "kind": "return"},
            {"from": "a0", "to": "a1", "text": "three", "kind": "async", "group": "g"},
            {"from": "a0", "to": "a2", "text": "four", "kind": "note"},
        ]
    )
    html = render_sequence(data)
    items = re.findall(
        r'<li class="vd-sequence-step" data-step="(\d+)">(.*?)</li>', html
    )
    assert [n for n, _ in items] == ["0", "1", "2", "3"]
    assert [t for _, t in items] == [
        "Actor 0 to Actor 1: one",
        "Actor 1 to Actor 0 (return): two",
        "Actor 0 to Actor 1 (async): three (group: g)",
        "Note over Actor 0 to Actor 2: four",
    ]
    assert 'data-copy="1. Actor 0 to Actor 1: one\n2. ' in html
    assert '<ol class="vd-sequence-steps" aria-label="Steps">' in html
    labels = {"a": "A"}
    assert step_text({"from": "a", "to": "a", "text": "t", "kind": "note"}, labels) == (
        "Note over A: t"
    )


def test_summary_is_plural_correct_and_regions_are_named() -> None:
    one = render_sequence(
        sample(actors=actors(1), steps=[{"from": "a0", "to": "a0", "text": "t"}])
    )
    assert "(1 step, 1 actor)" in one
    assert "(3 steps, 3 actors)" in render_sequence(sample())
    html = render_sequence(sample(title="T"))
    assert 'role="region" tabindex="0" aria-label="T (scrollable)"' in html
    assert 'class="vb sequence vd-sequence"' in html and 'class="vb-alt ' in html


def test_hostile_text_is_escaped() -> None:
    bad = "<script>alert(1)</script><img src=x onerror=1>"
    html = render_sequence(
        sample(
            title=bad,
            desc=bad,
            actors=[{"id": "a0", "label": bad}, *actors(3)[1:]],
            steps=[{"from": "a0", "to": "a1", "text": bad, "group": bad}],
        )
    )
    assert "<script>" not in html and "<img" not in html and "style=" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"steps": []}, "type"),
        ({"steps": [{"from": "zz", "to": "a1", "text": "t"}]}, "step-actor"),
        ({"steps": [{"from": "a0", "to": "zz", "text": "t"}]}, "step-actor"),
        ({"actors": actors(13)}, "too-many"),
        (
            {"actors": [{"id": "a", "label": "x"}, {"id": "a", "label": "y"}]},
            "actor-duplicate",
        ),
        ({"steps": [{"from": "a0", "to": "a1", "text": "t", "kind": "loud"}]}, "type"),
        ({"steps": [{"from": "a0", "to": "a1"}]}, "missing-key"),
        ({"extra": 1}, "unknown-key"),
    ],
)
def test_spec_faults(change: dict[str, Any], rule: str) -> None:
    assert rule in rules_of(sample(**change))


def test_too_many_steps_and_missing_desc_are_faults() -> None:
    steps = [{"from": "a0", "to": "a1", "text": "t"}] * 201
    assert "too-many" in rules_of(sample(steps=steps))
    data = sample()
    del data["desc"]
    assert "missing-key" in rules_of(data)
    assert rules_of(sample(title="t")) == []


def test_registered_and_renders_through_the_page() -> None:
    assert "sequence" in COMPONENTS
    doc = (FIXTURES / "rich-sequence.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert body.count("vd-sequence-row") >= 10 and "vb-error" not in body


def test_stress_fixture_validates_and_stays_escaped() -> None:
    doc = (FIXTURES / "rich-sequence-stress.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "<img" not in body and "<script>alert" not in body
    assert "style=" not in body and "vb-error" not in body
    assert body.count('class="vd-sequence-step"') >= 200


def test_interact_steps_are_in_order_for_focus_and_have_a_floor_height() -> None:
    html = render_sequence(sample())
    order = re.findall(r'<li class="vd-sequence-step" data-step="(\d+)"', html)
    assert order == ["0", "1", "2"]
    rows = re.findall(r'class="vd-sequence-row[^"]*" data-step="(\d+)"', html)
    assert rows == order
    css = (STATIC / "css" / "57-sequence.css").read_text()
    assert "min-block-size: 44px" in css and "outline-offset: -2px" in css


def test_interact_script_has_readout_roving_focus_and_escape() -> None:
    js = (STATIC / "sequence.js").read_text()
    assert "aria-live" in js and "'polite'" in js
    assert "tabIndex = li === active ? 0 : -1" in js
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "Escape"):
        assert key in js
    assert "style" not in js.replace(
        "only classes change", ""
    )  # no inline style writes
    assert "sequence.enhanceSequence" in (STATIC / "blocks.js").read_text()


def test_interact_no_tooltip_and_text_stays_inside_the_scroll_region() -> None:
    html = render_sequence(sample())
    assert 'role="tooltip"' not in html and "title=" not in html
    geo = layout(
        actors(3), [{"from": "a2", "to": "a2", "text": "w" * 60, "kind": "async"}]
    )
    row = geo.rows[0]
    longest = max(len(line) for line in row.lines) * CHAR_W
    assert row.text_x + longest + 1 <= geo.width


def test_css_print_block_is_last_and_uses_tokens_only() -> None:
    css = (STATIC / "css" / "57-sequence.css").read_text()
    assert css.rstrip().rsplit("@media", 1)[1].startswith(" print")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    assert "sticky" not in css and "overflow-wrap: anywhere" not in css
