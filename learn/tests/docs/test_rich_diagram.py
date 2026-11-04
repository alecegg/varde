"""The diagram component: spec, layout, SVG markup and (slow tier) interactions."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check_props
from varde_learn.docs.pages.blocks.diagrams import DIAGRAM, MAX_EDGES, MAX_NODES
from varde_learn.docs.pages.blocks_render.diagram_layout import (
    Box,
    EdgeSpec,
    Layout,
    NodeSpec,
    layout_graph,
)
from varde_learn.docs.pages.blocks_render.diagrams import (
    collapse,
    copy_text,
    diagram_states,
    render_diagram,
)
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.serve import PageServer

NODES = [
    {"id": "user", "label": "User", "shape": "rounded", "detail": "A <b>person</b>"},
    {"id": "gw", "label": "Gateway", "group": "edge", "detail": "Terminates TLS"},
    {"id": "api", "label": "API server with a long name", "group": "core"},
    {"id": "db", "label": "Database", "group": "core", "shape": "cylinder"},
    {"id": "ok", "label": "Healthy?", "shape": "diamond"},
]
EDGES = [
    {"from": "user", "to": "gw", "label": "https"},
    {"from": "gw", "to": "api"},
    {"from": "api", "to": "db", "label": "sql", "style": "dashed"},
    {"from": "db", "to": "api", "label": "rows", "style": "dotted"},
    {"from": "user", "to": "db", "label": "direct"},
    {"from": "api", "to": "api", "label": "retry"},
    {"from": "db", "to": "ok"},
    {"from": "ok", "to": "user", "label": "loop back"},
]
GROUPS = [{"id": "edge", "label": "Edge"}, {"id": "core", "label": "Core"}]
PROPS: dict[str, Any] = {
    "kind": "graph",
    "title": "Request path",
    "nodes": NODES,
    "edges": EDGES,
    "groups": GROUPS,
}


def specs(props: dict[str, Any]) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    nodes = [
        NodeSpec(n["id"], n["label"], n.get("shape", "box"), n.get("group", ""))
        for n in props["nodes"]
    ]
    edges = [
        EdgeSpec(e["from"], e["to"], e.get("label", ""), e.get("style", "solid"))
        for e in props.get("edges", [])
    ]
    return nodes, edges


def lay(props: dict[str, Any], direction: str = "LR") -> Layout:
    nodes, edges = specs(props)
    frames = {g["id"]: g["label"] for g in props.get("groups", [])}
    return layout_graph(nodes, edges, direction, frames)


def segment_hits(a: tuple[float, float], b: tuple[float, float], box: Box) -> bool:
    for k in range(41):
        x = a[0] + (b[0] - a[0]) * k / 40
        y = a[1] + (b[1] - a[1]) * k / 40
        if (
            box.x + 0.5 < x < box.x + box.w - 0.5
            and box.y + 0.5 < y < box.y + box.h - 0.5
        ):
            return True
    return False


def assert_clean(layout: Layout) -> None:
    boxes = [n.box for n in layout.nodes]
    for i, first in enumerate(boxes):
        assert all(not first.overlaps(second) for second in boxes[i + 1 :]), (
            "nodes overlap"
        )
        assert first.x >= 0 and first.y >= 0
        assert first.x + first.w <= layout.width and first.y + first.h <= layout.height
    for edge in layout.edges:
        ends = {edge.spec.source, edge.spec.target}
        for node in layout.nodes:
            if node.spec.id in ends:
                continue
            for p, q in zip(edge.points, edge.points[1:], strict=False):
                assert not segment_hits(p, q, node.box), (edge.spec, node.spec.id)
    labels = [e.label_box for e in layout.edges if e.label_box is not None]
    for i, first in enumerate(labels):
        assert all(not first.overlaps(second) for second in labels[i + 1 :]), (
            "labels overlap"
        )


@pytest.mark.parametrize("direction", ["LR", "TB"])
def test_layout_is_clean_for_the_fixture_with_cycles_and_a_self_loop(
    direction: str,
) -> None:
    layout = lay(PROPS, direction)
    assert_clean(layout)
    assert len(layout.nodes) == len(NODES) and len(layout.edges) == len(EDGES)
    assert {f.lane for f in layout.frames} == {"edge", "core"}


@pytest.mark.parametrize("direction", ["LR", "TB"])
def test_group_frames_hold_their_nodes_and_never_overlap(direction: str) -> None:
    layout = lay(PROPS, direction)
    frames = {f.lane: f.box for f in layout.frames}
    for node in layout.nodes:
        if node.spec.lane:
            assert frames[node.spec.lane].overlaps(node.box)
        else:
            assert not any(f.overlaps(node.box) for f in frames.values())
    first, second = frames.values()
    assert not first.overlaps(second)


def test_layout_is_deterministic() -> None:
    assert lay(PROPS) == lay(PROPS)
    assert render_diagram(PROPS) == render_diagram(dict(PROPS))


def test_every_edge_ends_on_its_target_side_and_arrows_point_at_it() -> None:
    layout = lay(PROPS)
    boxes = {n.spec.id: n.box.grown(1.5) for n in layout.nodes}
    for edge in layout.edges:
        tip = edge.points[-1]
        box = boxes[edge.spec.target]
        assert box.x <= tip[0] <= box.x + box.w and box.y <= tip[1] <= box.y + box.h


def test_long_edge_is_routed_around_the_node_in_its_way() -> None:
    chain = {
        "kind": "graph",
        "nodes": [{"id": n, "label": n} for n in "abcd"],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
            {"from": "c", "to": "d"},
            {"from": "a", "to": "d"},
        ],
    }
    assert_clean(lay(chain, "TB"))


def test_cycle_and_self_loop_are_laid_out() -> None:
    props = {
        "kind": "graph",
        "nodes": [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
            {"from": "a", "to": "a"},
        ],
    }
    layout = lay(props)
    assert_clean(layout)
    first, second = layout.edges[0], layout.edges[1]
    assert first.points != tuple(reversed(second.points))  # parallel edges are apart


def test_sixty_nodes_lay_out_in_a_time_budget_and_stay_clean() -> None:
    nodes = [
        {
            "id": f"n{i}",
            "label": f"Node number {i}",
            "group": "g" if i % 4 == 0 else None,
        }
        for i in range(60)
    ]
    nodes = [{k: v for k, v in n.items() if v is not None} for n in nodes]
    edges = [
        {"from": f"n{i}", "to": f"n{(i * 7 + 3) % 60}", "label": "x"} for i in range(60)
    ]
    edges += [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(59)]
    props = {
        "kind": "graph",
        "nodes": nodes,
        "edges": edges,
        "groups": [{"id": "g", "label": "G"}],
    }
    started = time.perf_counter()
    layout = lay(props, "TB")
    assert time.perf_counter() - started < 2.0
    assert_clean(layout)
    assert layout == lay(props, "TB")


def test_collapsed_group_becomes_one_node_with_redirected_edges() -> None:
    nodes, edges = specs(PROPS)
    kept, moved = collapse(nodes, edges, {"core": "Core", "edge": "Edge"}, {"core"})
    ids = [n.id for n in kept]
    assert "api" not in ids and "db" not in ids and "group:core" in ids
    assert any(n.label == "Core (2)" for n in kept)
    assert ("gw", "group:core") in {(e.source, e.target) for e in moved}
    states = diagram_states(PROPS)
    assert [mask for mask, _ in states] == [0, 1, 2, 3]
    for _, layout in states:
        assert_clean(layout)


def test_render_marks_root_escapes_text_and_has_no_inline_style() -> None:
    html = render_diagram(PROPS)
    assert html.startswith('<div class="vb diagram" data-copy="')
    assert " style=" not in html and "<script" not in html
    assert "&lt;b&gt;person&lt;/b&gt;" in html and "<b>person" not in html
    assert html.count('class="vd-view"') == 4
    assert (
        html.count('role="region" tabindex="0" aria-label="Request path (scrollable)"')
        == 4
    )
    assert html.count(" hidden>") == 3  # only the expanded state shows without JS
    assert "vd-cylinder" in html and "vd-diamond" in html and "vd-rounded" in html
    assert (
        "vd-dashed" in html
        and "vd-dotted" in html
        and '<polygon class="vd-head"' in html
    )
    assert '<details class="vb-data">' in html and "Nodes and edges as text" in html
    assert 'data-node="gw"' in html and "Terminates TLS" in html


def test_diagram_is_registered_and_renders_through_the_registry() -> None:
    assert COMPONENTS["diagram"].spec is DIAGRAM
    assert COMPONENTS["diagram"].render(PROPS, None) == render_diagram(PROPS)


def test_copy_entry_text_lists_nodes_and_edges() -> None:
    text = copy_text(PROPS)
    assert text.startswith("Request path")
    assert (
        "- Database [cylinder]" in text
        and "- Gateway -> API server with a long name" in text
    )
    assert "- Database -> API server with a long name: rows" in text
    assert "- API server with a long name -> API server with a long name: retry" in text


def test_spec_example_validates_and_lists_nodes() -> None:
    result = parse_lines(DIAGRAM.example)
    assert result.errors == []
    assert check_props("diagram", result.statements[0].props, 1) == []
    assert any(line.startswith("nodes") for line in DIAGRAM.fields)


def rules(props: dict[str, Any]) -> set[str]:
    return {e.rule for e in check_props("diagram", props, 1)}


def test_validation_names_each_fault() -> None:
    base = {
        "kind": "graph",
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
    }
    assert rules(base) == set()
    assert "unknown-key" in rules({**base, "mermaid": "graph TD"})
    assert "missing-key" in rules({"kind": "graph"})
    assert "node-duplicate" in rules({**base, "nodes": base["nodes"] * 2})
    assert "edge-target" in rules({**base, "edges": [{"from": "a", "to": "zz"}]})
    assert "type" in rules({**base, "kind": "sequence"})
    assert "type" in rules({**base, "direction": "RL"})
    assert "type" in rules(
        {**base, "edges": [{"from": "a", "to": "b", "style": "wavy"}]}
    )
    assert "type" in rules(
        {"kind": "graph", "nodes": [{"id": "a", "label": "A", "shape": "star"}]}
    )
    assert "node-group" in rules(
        {"kind": "graph", "nodes": [{"id": "a", "label": "A", "group": "q"}]}
    )
    assert "group-empty" in rules({**base, "groups": [{"id": "q", "label": "Q"}]})
    four = [{"id": f"g{i}", "label": "G"} for i in range(4)]
    assert "too-many" in rules({**base, "groups": four})


def test_validation_caps_nodes_and_edges() -> None:
    nodes = [{"id": f"n{i}", "label": "n"} for i in range(MAX_NODES + 1)]
    assert "too-many" in rules({"kind": "graph", "nodes": nodes})
    edges = [{"from": "n0", "to": "n1"}] * (MAX_EDGES + 1)
    assert "too-many" in rules({"kind": "graph", "nodes": nodes[:2], "edges": edges})


def test_tree_needs_one_parent_and_no_cycle() -> None:
    nodes = [{"id": n, "label": n} for n in "abc"]
    two_parents = [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}]
    assert "tree-parent" in rules(
        {"kind": "tree", "nodes": nodes, "edges": two_parents}
    )
    ring = [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]
    assert "tree-cycle" in rules({"kind": "tree", "nodes": nodes, "edges": ring})
    fine = [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}]
    assert rules({"kind": "tree", "nodes": nodes, "edges": fine}) == set()
    assert_clean(lay({"kind": "tree", "nodes": nodes, "edges": fine}, "TB"))


# ---- Chromium (slow tier) ---------------------------------------------------

DOC = """# Diagram

```ui id=d
d = diagram(
  kind: "graph",
  title: "Request path",
  groups: [{"id": "edge", "label": "Edge"}, {"id": "core", "label": "Core"}],
  nodes: [
    {"id": "user", "label": "User", "shape": "rounded", "detail": "A person"},
    {"id": "gw", "label": "Gateway", "group": "edge", "detail": "Terminates TLS"},
    {"id": "api", "label": "API", "group": "core"},
    {"id": "db", "label": "Database", "group": "core", "shape": "cylinder"},
    {"id": "log", "label": "Audit log", "shape": "diamond"},
  ],
  edges: [
    {"from": "user", "to": "gw", "label": "https"},
    {"from": "gw", "to": "api"},
    {"from": "api", "to": "db", "label": "sql"},
    {"from": "gw", "to": "log", "style": "dashed"},
  ],
)
```
"""


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(
        viewport={"width": 900, "height": 700}, has_touch=True
    )
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def open_page(tmp_path: Path, shared_page: Any) -> Iterator[Any]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    problems: list[str] = []
    shared_page.on("pageerror", lambda error: problems.append(str(error)))
    shared_page.goto(f"http://127.0.0.1:{server.port}/")
    shared_page.wait_for_selector(".vd-view [role=button]")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".vd-view [role=button]")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


def visible_view(page: Any) -> Any:
    return page.locator(".vd-view:not([hidden])")


def node(page: Any, ident: str) -> Any:
    return visible_view(page).locator(f'.vd-node[data-id="{ident}"]')


def view_box(page: Any) -> list[float]:
    raw = visible_view(page).locator("svg").get_attribute("viewBox")
    return [float(v) for v in (raw or "").split()]


@pytest.mark.slow
def test_interact_pan_and_zoom_by_buttons_keys_wheel_and_fit(open_page: Any) -> None:
    page = open_page
    home = view_box(page)
    page.get_by_role("button", name="Zoom in").first.click()
    assert view_box(page)[2] < home[2]
    page.get_by_role("button", name="Fit whole diagram").first.click()
    assert view_box(page) == home
    visible_view(page).focus()
    page.keyboard.press("+")
    zoomed = view_box(page)
    assert zoomed[2] < home[2]
    page.keyboard.press("ArrowRight")
    assert view_box(page)[0] != zoomed[0]
    page.keyboard.press("0")
    assert view_box(page) == home
    svg = visible_view(page).locator("svg")
    svg.dispatch_event(
        "wheel", {"ctrlKey": True, "deltaY": -100, "clientX": 100, "clientY": 100}
    )
    assert view_box(page)[2] < home[2]


@pytest.mark.slow
def test_interact_two_pointer_pinch_zooms(open_page: Any) -> None:
    page = open_page
    home = view_box(page)
    page.evaluate(
        """() => {
          const svg = document.querySelector('.vd-view:not([hidden]) svg');
          const fire = (type, id, x, y) => svg.dispatchEvent(new PointerEvent(type,
            {pointerId: id, clientX: x, clientY: y, buttons: 1, bubbles: true}));
          fire('pointerdown', 1, 100, 100); fire('pointerdown', 2, 140, 100);
          fire('pointermove', 2, 240, 100);
          fire('pointerup', 2, 240, 100); fire('pointerup', 1, 100, 100);
        }"""
    )
    assert view_box(page)[2] < home[2]


@pytest.mark.slow
def test_interact_focus_highlights_neighbours_and_select_announces_detail(
    open_page: Any,
) -> None:
    page = open_page
    node(page, "gw").focus()
    classes = {
        i: (node(page, i).get_attribute("class") or "")
        for i in ("user", "api", "log", "db")
    }
    assert (
        "vd-near" in classes["user"]
        and "vd-near" in classes["api"]
        and "vd-near" in classes["log"]
    )
    assert "vd-dim" in classes["db"]
    hot = visible_view(page).locator(".vd-edge.vd-hot")
    assert hot.count() == 3
    page.keyboard.press("Enter")
    assert node(page, "gw").get_attribute("aria-pressed") == "true"
    status = page.locator(".vd-detail")
    assert status.get_attribute("aria-live") == "polite"
    assert "Terminates TLS" in (status.text_content() or "")
    node(page, "db").click()
    assert node(page, "db").get_attribute("aria-pressed") == "true"
    assert node(page, "gw").get_attribute("aria-pressed") == "false"


@pytest.mark.slow
def test_interact_arrow_keys_follow_edges(open_page: Any) -> None:
    page = open_page
    node(page, "user").focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.dataset.id") == "gw"
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.dataset.id") == "api"
    page.keyboard.press("ArrowLeft")
    assert page.evaluate("document.activeElement.dataset.id") == "gw"


@pytest.mark.slow
def test_interact_group_collapse_and_expand_relays_out_edges(open_page: Any) -> None:
    page = open_page
    head = visible_view(page).locator('.vd-group-head[data-group="core"]')
    assert head.get_attribute("aria-expanded") == "true"
    edges_open = visible_view(page).locator(".vd-edge").count()
    head.click(position={"x": 30, "y": 10})
    assert page.locator(".vd-view:not([hidden])").count() == 1
    assert visible_view(page).locator(".vd-node[data-id='db']").count() == 0
    collapsed = visible_view(page).locator(".vd-super")
    assert collapsed.get_attribute("aria-expanded") == "false"
    assert visible_view(page).locator(".vd-edge").count() < edges_open
    page.keyboard.press("Enter")
    assert visible_view(page).locator(".vd-node[data-id='db']").count() == 1
    assert visible_view(page).locator(".vd-edge").count() == edges_open


@pytest.mark.slow
def test_interact_works_with_touch_taps_and_no_hover(open_page: Any) -> None:
    page = open_page  # touch page: a second context crashes single-process Chromium
    page.set_viewport_size({"width": 390, "height": 800})
    node(page, "gw").tap()
    assert node(page, "gw").get_attribute("aria-pressed") == "true"
    assert "Terminates TLS" in (page.locator(".vd-detail").text_content() or "")
    visible_view(page).locator('.vd-group-head[data-group="core"]').tap()
    assert visible_view(page).locator(".vd-super").count() == 1
    page.set_viewport_size({"width": 900, "height": 700})


@pytest.mark.slow
def test_interact_focused_node_sits_inside_the_view_with_a_margin(
    open_page: Any,
) -> None:
    page = open_page
    page.set_viewport_size({"width": 320, "height": 700})
    node(page, "db").focus()
    inside = page.evaluate(
        """() => {
          const view = document.querySelector('.vd-view:not([hidden])');
          const v = view.getBoundingClientRect();
          const r = document.activeElement.getBoundingClientRect();
          return [r.left - v.left, v.right - r.right,
            r.top - v.top, v.bottom - r.bottom];
        }"""
    )
    assert all(gap >= 3.5 for gap in inside), inside
    page.set_viewport_size({"width": 900, "height": 700})


def test_served_html_has_no_script_only_controls() -> None:
    assert "vb-controls" not in render_diagram(PROPS)


@pytest.mark.slow
def test_interact_one_control_bar_per_diagram_acting_on_the_shown_view(
    open_page: Any,
) -> None:
    page = open_page
    assert page.locator(".diagram .vb-controls").count() == 1
    visible_view(page).locator('.vd-group-head[data-group="core"]').click(
        position={"x": 30, "y": 10}
    )
    assert page.locator(".diagram .vb-controls").count() == 1
    home = view_box(page)
    page.get_by_role("button", name="Zoom in").click()
    assert view_box(page)[2] < home[2]
    page.get_by_role("button", name="Fit whole diagram").click()
    assert view_box(page) == home


@pytest.mark.slow
def test_interact_diagram_fits_the_width_on_first_paint(open_page: Any) -> None:
    page = open_page
    page.set_viewport_size({"width": 375, "height": 800})
    page.reload()
    page.wait_for_selector(".vd-view [role=button]")
    page.wait_for_timeout(600)
    sizes = page.evaluate(
        """() => {
          const view = document.querySelector('.vd-view:not([hidden])');
          const svg = view.querySelector('svg');
          return [svg.getBoundingClientRect().width, view.clientWidth,
            view.getBoundingClientRect().height, svg.getBoundingClientRect().height];
        }"""
    )
    natural = page.evaluate("Number(document.querySelector('.vd-svg').dataset.natW)")
    assert sizes[0] < natural  # scaled down from natural size
    assert sizes[0] <= sizes[1]  # the whole graph is inside the view at first paint
    page.get_by_role("button", name="Fit whole diagram").click()
    whole = page.evaluate(
        "document.querySelector('.vd-svg').getBoundingClientRect().width"
    )
    assert whole <= sizes[0] + 1  # Fit never shows less than first paint
    assert sizes[2] <= sizes[3] + 4  # the view is as tall as its content
    page.set_viewport_size({"width": 900, "height": 700})
