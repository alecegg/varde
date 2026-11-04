"""The data-model graph layout: placement, routing, relation text, inference, faults."""

from __future__ import annotations

import html
import re
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import type_text
from varde_learn.docs.pages.blocks.backend import validate_data_model
from varde_learn.docs.pages.blocks_render.backend import render_data_model
from varde_learn.docs.pages.blocks_render.er import (
    declared_relations,
    inferred_relations,
    relation_text,
)
from varde_learn.docs.pages.blocks_render.er_layout import (
    BOX_W,
    edges_cross_boxes,
    place,
    route,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
HOSTILE = '<img src=x onerror=alert(1)> "q" &amp; <script>alert(1)</script>'


def entity(name: str, /, *relations: tuple[str, str], **fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "key": "id",
        "fields": {"id": "uuid", **fields},
    }
    if relations:
        out["relations"] = [{"to": to, "kind": kind} for to, kind in relations]
    return out


def model(*entities: dict[str, Any], **extra: object) -> dict[str, object]:
    return {"entity": list(entities), **extra}


def test_list_output_is_unchanged_without_layout() -> None:
    data = model(entity("a", ("b", "one-to-many")), entity("b", name="text"))
    plain = render_data_model(data)
    assert render_data_model({**data, "layout": "list"}) == plain
    assert "vd-er" not in plain
    assert 'class="vb data-model"' in plain and 'class="vb-grid"' in plain


def test_placement_is_deterministic_and_grid_shaped() -> None:
    counts = [2, 9, 1, 3, 4, 0, 2]
    assert place(counts) == place(counts)
    grid = place(counts)
    assert grid.cols == 3 and len(grid.row_top) == 3
    cells = [(b.col, b.grid_row) for b in grid.boxes[:4]]
    assert cells == [(0, 0), (1, 0), (2, 0), (0, 1)]
    taller = grid.boxes[1].h
    assert taller > grid.boxes[0].h
    assert grid.row_bottom[0] - grid.row_top[0] == taller


def on_edge(point: tuple[float, float], box: Any) -> bool:
    x, y = point
    inside_x = box.x <= x <= box.x + BOX_W
    inside_y = box.y <= y <= box.bottom
    touches = x in (box.x, box.x + BOX_W) or y in (box.y, box.bottom)
    return inside_x and inside_y and touches


@pytest.mark.parametrize("count", [2, 3, 5, 9, 30])
def test_lines_touch_card_edges_and_cross_no_card(count: int) -> None:
    grid = place([2 + i % 8 for i in range(count)])
    for lane, (i, j) in enumerate(
        (i, j) for i in range(count) for j in range(count) if (i * 7 + j) % 5 == 0
    ):
        a, b = grid.boxes[i], grid.boxes[j]
        points = route(grid, a, b, lane)
        assert on_edge(points[0], a) and on_edge(points[-1], b), (i, j, points)
        assert all((x0 == x1 or y0 == y1) for (x0, y0), (x1, y1) in pairwise(points))
        assert not edges_cross_boxes(grid, points), (i, j, points)
        assert all(0 <= x <= grid.width and 0 <= y <= grid.height for x, y in points)


def test_self_relation_is_a_loop_on_one_edge() -> None:
    grid = place([3])
    box = grid.boxes[0]
    points = route(grid, box, box, 0)
    assert len(points) == 4
    assert on_edge(points[0], box) and on_edge(points[-1], box)


def graph_html(*entities: dict[str, Any]) -> str:
    return render_data_model(model(*entities, layout="graph"))


def text_of(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def test_text_list_matches_the_relations() -> None:
    markup = graph_html(
        entity("order", ("customer", "many-to-one"), ("order", "one-to-many")),
        entity("customer", ("order", "one-to-one"), ("order", "many-to-many")),
    )
    items = re.findall(r'<li class="vd-er-rel"[^>]*>(.*?)</li>', markup)
    assert [text_of(i) for i in items] == [
        "order n to 1 customer",
        "order 1 to n order",
        "customer 1 to 1 order",
        "customer n to n order",
    ]
    assert len(re.findall(r'<g class="vd-er-edge"', markup)) == 4
    assert "drawing" in markup and 'aria-hidden="true"' in markup


def test_relation_without_cardinality_reads_relates_to() -> None:
    names = ["a", "b"]
    rel = declared_relations([{"name": "a", "relations": [{"to": "b"}]}, {"name": "b"}])
    assert relation_text(names, rel[0]) == "a relates to b"


def test_relations_are_inferred_from_id_fields_only_when_undeclared() -> None:
    entities = [
        entity("customer"),
        entity("order", ("customer", "many-to-one"), customer_id="uuid"),
        entity("line", order_id="uuid", Customer_ID="uuid", parent_id="uuid"),
    ]
    declared = declared_relations(entities)
    inferred = inferred_relations(entities, declared)
    assert [(r.source, r.target, r.field) for r in inferred] == [
        (2, 1, "order_id"),
        (2, 0, "Customer_ID"),
    ]
    markup = graph_html(*entities)
    assert "line n to 1 order (inferred from field order_id)" in text_of(markup)
    assert markup.count("vd-er-inferred") == 2


def test_foreign_key_fields_link_to_the_target_card() -> None:
    markup = graph_html(
        entity("customer"),
        entity("order", ("customer", "many-to-one"), customer_id="uuid"),
    )
    link = re.search(r'<a class="vd-er-fk" href="#([^"]+)">', markup)
    assert link
    assert f'id="{link.group(1)}"' in markup
    assert "customer_id" in text_of(markup)


def test_change_badges_and_markers_survive_in_graph() -> None:
    data = model(
        {
            **entity("a", total={"type": "int", "change": "modified", "was": "text"}),
            "change": "added",
        },
        entity("b"),
        layout="graph",
    )
    markup = render_data_model(data)
    assert "vd-change-badge" in markup and "vd-change-card" in markup
    assert "+ a" in markup and "~ total: int" in markup
    assert "Changes: " in markup


def test_hostile_text_is_escaped_and_no_style_or_script() -> None:
    markup = graph_html(
        entity(HOSTILE, (HOSTILE, "one-to-one"), **{HOSTILE: HOSTILE}),
    )
    assert "<script" not in markup and "<img" not in markup
    assert "style=" not in markup and "onclick" not in markup
    assert html.escape(HOSTILE) in markup


def test_many_fields_show_a_more_row_and_cards_list_all() -> None:
    fields = {f"f{i}": "t" for i in range(200)}
    markup = graph_html(entity("wide", **fields))
    assert "+195 more" in markup
    assert markup.count("<td>f") + markup.count(">f1") >= 200


def test_thirty_entities_pass_and_thirty_one_fault() -> None:
    def names(n: int) -> list[dict[str, Any]]:
        return [entity(f"e{i}", (f"e{(i + 1) % n}", "one-to-many")) for i in range(n)]

    ok = validate_data_model(model(*names(30), layout="graph"))
    assert ok == []
    faults = validate_data_model(model(*names(31), layout="graph"))
    assert [f.rule for f in faults] == ["graph-size"]
    assert validate_data_model(model(*names(31))) == []


def test_unknown_layout_and_unknown_entity_fault() -> None:
    assert [f.rule for f in validate_data_model(model(entity("a"), layout="ring"))] == [
        "type"
    ]
    bad = model(entity("a", ("ghost", "one-to-one")), layout="graph")
    assert [f.rule for f in validate_data_model(bad)] == ["relation-target"]


def test_render_is_deterministic() -> None:
    data = model(
        entity("a", ("b", "one-to-many")), entity("b", a_id="uuid"), layout="graph"
    )
    assert render_data_model(data) == render_data_model(data)


@pytest.mark.parametrize("name", ["rich-er.md", "rich-er-stress.md"])
def test_fixtures_render_without_error(name: str) -> None:
    body = render_page((FIXTURES / name).read_text(), name).body
    assert "vb-error" not in body and "vd-er-svg" in body
    assert "<script" not in body and "style=" not in body


def test_help_text_lists_the_layout_prop() -> None:
    text = type_text("data-model")
    assert "layout" in text and "graph" in text
