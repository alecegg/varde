"""The state component: flow-layout adapter, loops, faults, text alternative."""

from __future__ import annotations

import itertools
import math
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.diagram_layout import (
    EdgeSpec,
    layout_graph,
    loop_room,
)
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.blocks_render.state import render_state
from varde_learn.docs.pages.blocks_render.state_graph import (
    graph_specs,
    loop_labels,
    states_of,
    transition_text,
    transitions_of,
    unreachable_ids,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
STATIC = Path(str(files("varde_learn.docs.pages").joinpath("static")))


def sample(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "desc": "d",
        "states": [
            {"id": "idle", "label": "Idle", "kind": "initial"},
            {"id": "run", "label": "Running"},
            {"id": "done", "label": "Done", "kind": "final"},
            {"id": "bad", "label": "Failed", "kind": "error"},
        ],
        "transitions": [
            {"from": "idle", "to": "run", "label": "start"},
            {"from": "run", "to": "done", "label": "finish", "guard": "ok"},
            {"from": "run", "to": "bad", "label": "crash"},
            {"from": "bad", "to": "run", "label": "retry"},
            {"from": "run", "to": "run", "label": "beat"},
        ],
    }
    return {**data, **extra}


def rules_of(data: dict[str, Any]) -> list[str]:
    return [e.rule for e in check_props("state", data, 1)]


def specs_of(data: dict[str, Any]):
    states = states_of(data)
    moves = transitions_of(data, {str(s["id"]) for s in states})
    return states, moves, graph_specs(states, moves, "S")


def test_adapter_output_equals_flow_input() -> None:
    _, moves, (nodes, edges) = specs_of(sample())
    assert [n.id for n in nodes] == ["S", "idle", "run", "done", "bad"]
    assert [(e.source, e.target) for e in edges] == [
        ("S", "idle"),
        ("idle", "run"),
        ("run", "done"),
        ("run", "bad"),
        ("bad", "run"),
        ("run", "run"),
    ]
    assert edges[2].label == "finish [ok]" and len(moves) == 5
    assert nodes[4].label == "✕ Failed"


def test_self_loops_merge_per_state_and_loop_back_is_routed() -> None:
    data = sample(
        transitions=[
            *sample()["transitions"],
            {"from": "run", "to": "run", "label": "tick", "guard": "g"},
        ]
    )
    _, moves, (nodes, edges) = specs_of(data)
    assert loop_labels(moves) == {"run": "beat; tick [g]"}
    assert sum(e.source == e.target for e in edges) == 1
    lay = layout_graph(nodes, edges, "TB")
    back = next(
        e for e in lay.edges if (e.spec.source, e.spec.target) == ("bad", "run")
    )
    assert back.points[0][1] > back.points[-1][1]  # drawn upward: a loop-back
    assert all(math.isfinite(c) for e in lay.edges for p in e.points for c in p)


def test_layout_boxes_and_loop_labels_never_overlap_and_stay_inside() -> None:
    wide = [{"id": f"w{n}", "label": f"Wide state {n}"} for n in range(6)]
    wide[0]["kind"] = "initial"
    moves = [{"from": "w0", "to": f"w{n}", "label": "go"} for n in range(1, 6)]
    loops = [{"from": f"w{n}", "to": f"w{n}", "label": "loop " * 6} for n in range(6)]
    moves += loops
    for data in (sample(), sample(states=wide, transitions=moves)):
        _, _, (nodes, edges) = specs_of(data)
        lay = layout_graph(nodes, edges, "TB")
        boxes = [n.box for n in lay.nodes]
        for a, b in itertools.combinations(boxes, 2):
            assert not a.overlaps(b)
        loops = {
            i: e.label_box
            for i, e in enumerate(lay.edges)
            if e.spec.source == e.spec.target and e.label_box
        }
        assert loops
        found = re.search(r'width="([\d.]+)"', render_state(data))
        assert found
        width = float(found.group(1))
        for box in loops.values():
            assert box.x >= 0 and box.y >= 0 and box.x + box.w <= width
            assert not any(box.overlaps(b) for b in boxes)
        for one, two in itertools.combinations(loops.values(), 2):
            assert not one.overlaps(two)


def test_render_is_deterministic_and_finite() -> None:
    assert render_state(sample()) == render_state(sample())
    html = render_state(sample())
    assert "NaN" not in html and "None" not in html and "inf" not in html


def test_kinds_have_shapes_and_words_not_only_colour() -> None:
    html = render_state(sample())
    assert "vd-state-dot" in html and "<title>initial state marker</title>" in html
    assert html.count("vd-state-ring") == 1  # final: double border
    assert "<title>Failed, error state</title>" in html and "✕ Failed" in html
    assert "<title>Idle, initial state</title>" in html
    assert '<li class="vd-state-item">Idle (initial state)</li>' in html


def test_unreachable_state_is_marked_by_dash_title_and_list() -> None:
    data = sample(states=[*sample()["states"], {"id": "x", "label": "Lost"}])
    states, moves, _ = specs_of(data)
    assert unreachable_ids(states, moves) == {"x"}
    html = render_state(data)
    assert "vd-state-unreachable" in html and "Lost, state, unreachable" in html
    assert "Lost (state, unreachable from the initial state)" in html
    assert unreachable_ids(*specs_of(sample())[:2]) == set()
    assert rules_of(data) == []  # a warning in the drawing, not a fault


def test_text_alternative_equals_the_transitions() -> None:
    html = render_state(sample())
    items = re.search(r'<ol class="vd-state-moves"[^>]*>(.*?)</ol>', html, re.DOTALL)
    assert items
    assert re.findall(r">([^<]+)</li>", items.group(1)) == [
        "Idle to Running on start",
        "Running to Done on finish [ok]",
        "Running to Failed on crash",
        "Failed to Running on retry",
        "Running to Running on beat",
    ]
    assert "1. Idle to Running on start" in html.split("data-copy=")[1]
    labels = {"a": "A"}
    assert (
        transition_text({"from": "a", "to": "a", "guard": "g"}, labels) == "A to A [g]"
    )


def test_summary_is_plural_correct_and_region_is_named() -> None:
    one = render_state(
        {"desc": "d", "states": [{"id": "a", "label": "A", "kind": "initial"}]}
    )
    assert "(1 state, 0 transitions)" in one and "<ol" not in one
    assert "(4 states, 5 transitions)" in render_state(sample())
    html = render_state(sample(title="T"))
    assert 'role="region" tabindex="0" aria-label="T (scrollable)"' in html
    assert 'class="vb state vd-state"' in html and 'class="vb-alt ' in html


def test_forty_states_and_many_transitions_render() -> None:
    states = [{"id": f"s{n}", "label": f"S{n}"} for n in range(40)]
    states[0]["kind"] = "initial"
    moves = [{"from": f"s{n % 40}", "to": f"s{(n * 7 + 3) % 40}"} for n in range(200)]
    data = sample(states=states, transitions=moves)
    assert rules_of(data) == []
    html = render_state(data)
    assert html.count('class="vd-state-node') == 40 and "NaN" not in html
    assert "too-many" in rules_of(sample(states=[*states, {"id": "z", "label": "Z"}]))


def test_hostile_text_is_escaped() -> None:
    bad = "<script>alert(1)</script><img src=x onerror=1>"
    html = render_state(
        sample(
            title=bad,
            desc=bad,
            states=[{"id": "idle", "label": bad, "kind": "initial", "note": bad}],
            transitions=[{"from": "idle", "to": "idle", "label": bad, "guard": bad}],
        )
    )
    assert "<script>" not in html and "<img" not in html and "style=" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"transitions": [{"from": "zz", "to": "run"}]}, "transition-state"),
        ({"transitions": [{"from": "run", "to": "zz"}]}, "transition-state"),
        ({"states": [{"id": "a", "label": "A"}]}, "no-initial"),
        (
            {"states": [{"id": "a", "label": "A", "kind": "initial"}] * 2},
            "two-initial",
        ),
        (
            {"states": [{"id": "a", "label": "A", "kind": "initial"}] * 2},
            "state-duplicate",
        ),
        ({"states": [{"id": "a", "label": "A", "kind": "loud"}]}, "type"),
        ({"states": []}, "type"),
        ({"transitions": [{"from": "run"}]}, "missing-key"),
        ({"extra": 1}, "unknown-key"),
    ],
)
def test_spec_faults(change: dict[str, Any], rule: str) -> None:
    assert rule in rules_of(sample(**change))


def test_missing_desc_is_a_fault_and_title_is_optional() -> None:
    data = sample()
    del data["desc"]
    assert "missing-key" in rules_of(data)
    assert rules_of(sample(title="t")) == []


def test_registered_and_fixtures_render_through_the_page() -> None:
    assert "state" in COMPONENTS
    for name, floor in (("rich-state", 2), ("rich-state-stress", 2)):
        doc = (FIXTURES / f"{name}.md").read_text()
        assert check(doc) == []
        body = render_page(doc, "t.md").body
        assert body.count('class="vb state vd-state"') == floor
        assert "<img" not in body and "<script>alert" not in body
        assert "style=" not in body and "vb-error" not in body


def test_stress_fixture_has_forty_states() -> None:
    body = render_page((FIXTURES / "rich-state-stress.md").read_text(), "t.md").body
    assert body.count('class="vd-state-node vd-state-') >= 45


def test_css_print_block_is_last_and_uses_tokens_only() -> None:
    css = (STATIC / "css" / "60-state.css").read_text()
    assert css.rstrip().rsplit("@media", 1)[1].startswith(" print")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    assert "sticky" not in css and "overflow-wrap: anywhere" not in css
    assert "position: relative" in css and "forced-colors" in css


def test_loop_room_reserves_label_width_only_for_loops() -> None:
    assert loop_room([EdgeSpec("a", "b", "go")]) == {}
    bare = loop_room([EdgeSpec("a", "a")])["a"]
    labelled = loop_room([EdgeSpec("a", "a", "tick tick"), EdgeSpec("a", "a", "x")])
    assert labelled["a"] > bare > 0


def test_loop_label_never_covers_a_neighbour_in_the_same_row() -> None:
    kids = [{"id": f"s{n}", "label": f"S{n}"} for n in range(1, 4)]
    states = [{"id": "r", "label": "Root", "kind": "initial"}, *kids]
    moves: list[dict[str, Any]] = [{"from": "r", "to": s["id"]} for s in kids]
    moves += [{"from": "s1", "to": "s1", "label": "retry with a long label"}]
    _, _, (nodes, edges) = specs_of(sample(states=states, transitions=moves))
    lay = layout_graph(nodes, edges, "TB")
    label = next(e.label_box for e in lay.edges if e.spec.source == e.spec.target)
    assert label is not None
    assert not any(label.overlaps(n.box) for n in lay.nodes)


def test_start_marker_is_a_dot_with_an_arrow_and_alt_names_it() -> None:
    html = render_state(sample())
    assert 'class="vd-state-start"' in html and "vd-state-dot" in html
    assert "initial state marker to Idle" in html
    assert "Idle (initial state)" in html


def test_no_start_marker_without_an_initial_state() -> None:
    data = sample(states=[{"id": "a", "label": "A"}], transitions=[])
    assert "vd-state-start" not in render_state(data)
