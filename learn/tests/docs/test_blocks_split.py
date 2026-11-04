"""The block code split by kind keeps every existing render output unchanged."""

from varde_learn.docs.pages.blocks import SPECS, check_props
from varde_learn.docs.pages.blocks import charts as chart_spec
from varde_learn.docs.pages.blocks import diagrams as diagram_spec
from varde_learn.docs.pages.blocks import flow as flow_spec
from varde_learn.docs.pages.blocks import tables as table_spec
from varde_learn.docs.pages.blocks_render import diagrams, flow, registry, tables

TABLE = {
    "columns": ["a", "b<"],
    "rows": [["1", "x&y"], ["2", "z"]],
    "caption": "Cap",
}
FLOW = {
    "title": "T",
    "step": [
        {"id": "a", "text": "A <b>", "next": ["b", "c"]},
        {"id": "b", "text": "B"},
        {"id": "c", "text": "C", "next": ["a"]},
    ],
}


def test_table_and_flow_render_as_before() -> None:
    # The table was upgraded by rb-table (scroll region, scopes, copy text).
    assert 'class="vb-table"' in tables.render_table(TABLE)
    # The flow was upgraded by rb-flow (server SVG, list kept as the text alternative).
    assert '<ol class="vb-flow">' in flow.render_flow(FLOW)
    assert registry.COMPONENTS["table"].render(TABLE, None) == tables.render_table(
        TABLE
    )
    assert registry.COMPONENTS["flow"].render(FLOW, None) == flow.render_flow(FLOW)


def test_specs_moved_with_their_validators() -> None:
    assert SPECS["table"] is table_spec.TABLE
    assert SPECS["flow"] is flow_spec.FLOW
    assert SPECS["chart"] is chart_spec.CHART
    assert check_props("table", TABLE, 1) == []
    assert check_props("flow", FLOW, 1) == []


def test_diagram_modules_wait_for_rb_diagram() -> None:
    assert not hasattr(diagrams, "render_flow") and not hasattr(
        diagrams, "render_table"
    )
    assert diagrams.__doc__ and diagram_spec.__doc__
    assert not hasattr(diagram_spec, "FLOW")


def test_block_scripts_are_es_modules_imported_by_blocks_js() -> None:
    from varde_learn.docs.pages.template import page_scripts, static_scripts

    parts = {"dom.js", "table.js", "tabs.js", "flow.js", "chart.js", "viewport.js"}
    assert parts <= set(static_scripts())
    assert parts.isdisjoint(page_scripts())
    assert page_scripts() == ("app.js", "blocks.js", "recap.js", "inputs_ordered.js")
