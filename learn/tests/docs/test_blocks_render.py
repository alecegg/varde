"""Typed block renderers: classed HTML, escaping, error cards, no unsafe markup."""

from __future__ import annotations

import re

import pytest
from varde_learn.docs.pages import blocks
from varde_learn.docs.pages.render import render_page

from .ui_fence import example_fence, ui_fence

HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(1)>'
UNSAFE = [r"<script", r"style=", r"\son[a-z]+=", r"foreignObject"]


def page(lang: str, body: str, id_: str = "b1") -> str:
    return render_page(ui_fence(lang, body, id_), "t.md").body


def example_page(name: str, old: str = "", new: str = "") -> str:
    statement = (
        blocks.SPECS[name].example.replace(old, new)
        if old
        else blocks.SPECS[name].example
    )
    return render_page(example_fence(statement), "t.md").body


@pytest.mark.parametrize("name", blocks.TYPES)
def test_every_example_renders_classed_html(name):
    out = example_page(name)
    assert 'class="vb' in out
    assert "vb-error" not in out
    for pattern in UNSAFE:
        assert not re.search(pattern, out), (name, pattern)


def test_hostile_every_field_escaped():
    model = (
        '[[entity]]\nname = "a<b>"\nkey = "id"\nfields = { id = "<i>x</i>" }\n'
        '[[entity.relations]]\nto = "a<b>"\nkind = "many-to-one"\n'
    )
    out = page("data-model", model)
    assert "a&lt;b&gt;" in out and "&lt;i&gt;" in out and "<i>" not in out
    endpoint = (
        'method = "GET"\npath = "/x<y>"\nauth = "<b>"\nsummary = "<u>"\n'
        'request = { "<k>" = "<v>" }\n[[responses]]\nstatus = 200\nbody = "<body>"\n'
    )
    out = page("endpoint", endpoint)
    for raw in ("<y>", "<b>", "<u>", "<k>", "<v>", "<body>"):
        assert raw not in out
    chart = (
        'kind = "line"\ntitle = "<t>"\nunit = "<u>"\nlabels = ["<l>"]\n'
        '[[series]]\nname = "<s>"\nvalues = [1]\n'
    )
    out = page("chart", chart)
    for raw in ("<t>", "<u>", "<l>", "<s>"):
        assert raw not in out
    states = (
        'screen = "<sc>"\n[empty]\nshows = "<e>"\n[loading]\nna = "<n>"\n'
        '[error]\nshows = "x"\n'
    )
    out = page("ui-states", states)
    for raw in ("<sc>", "<e>", "<n>"):
        assert raw not in out
    wire = 'title = "<w>"\ngrid = ["AB"]\n[regions]\nA = "<a>"\nB = "<b>"\n'
    out = page("wireframe", wire)
    assert "<a>" not in out and "<w>" not in out
    flow = 'title = "<f>"\n[[step]]\nid = "s"\ntext = "<x>"\nnext = ["s"]\n'
    out = page("flow", flow)
    assert "<f>" not in out and "<x>" not in out
    tbl = 'caption = "<c>"\ncolumns = ["<h>"]\nrows = [["<d>"], [3]]\n'
    out = page("table", tbl)
    for raw in ("<c>", "<h>", "<d>"):
        assert raw not in out


def test_markers():
    out = example_page("data-model")
    assert "vb-badge-key" in out and "vb-rel" in out and "many-to-one" in out
    out = example_page("endpoint")
    assert "vb-method" in out and "auth: bearer" in out and "vb-auth" in out
    assert "vb-auth-none" in example_page("endpoint", '"bearer"', '"none"')


def test_wireframe_ui_states_flow_table_chart_shapes():
    assert "<svg" in example_page("wireframe")
    states = example_page("ui-states")
    assert "vb-state-empty" in states and "vb-state-loading" in states
    assert "vb-na" in example_page(
        "ui-states", '{"shows": "Skeleton rows"}', '{"na": "instant"}'
    )
    flow = example_page("flow")
    assert "vb-step" in flow and "vb-branch" in flow
    assert "<table" in example_page("table")
    bar = example_page("chart")
    assert "<svg" in bar and "vb-bar" in bar
    line = example_page("chart", '"bar"', '"line"')
    assert "vb-line" in line


def test_invalid_block_renders_error_card_with_errors():
    out = page("endpoint", 'method = "GET"\npath = "/x"\n[[responses]]\nstatus = 200\n')
    assert "vb-error" in out and "endpoint-auth" in out


def test_parse_error_renders_one_error_card():
    out = render_page("```ui id=t\nt = table(columns: \n```\n", "t.md").body
    assert "vb-error" in out and "ui block has" in out


def test_old_typed_fence_renders_a_removed_card():
    out = render_page("```table id=t\ncolumns = []\n```\n", "t.md").body
    assert "vb-error" in out and "toml-fence-removed" in out


def test_chart_rejects_non_finite():
    out = render_page(
        '```ui id=c\nc = chart(kind: "bar", labels: ["a"], '
        'series: [{"name": "s", "values": ["x"]}])\n```\n',
        "t.md",
    ).body
    assert "vb-error" in out


def test_negative_values_and_flat_series_render():
    body = (
        'kind = "bar"\nlabels = ["a", "b"]\n[[series]]\nname = "s"\nvalues = [-2, 3]\n'
    )
    assert "vb-bar" in page("chart", body)
    flat = 'kind = "line"\nlabels = ["a"]\n[[series]]\nname = "s"\nvalues = [0]\n'
    assert "vb-line" in page("chart", flat)


def test_error_card_escapes_hostile_text():
    text = f"t = table({HOSTILE.replace(chr(34), '')}: 1)\n"
    out = render_page(f"```ui id=t\n{text}```\n", "t.md").body
    assert "vb-error" in out
    assert "<script" not in out and "<img" not in out
