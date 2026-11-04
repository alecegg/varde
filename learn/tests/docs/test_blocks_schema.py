"""Typed block schemas, ids, fence-offset errors and the `blocks` command."""

from __future__ import annotations

import re
from importlib.resources import files

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages import blocks
from varde_learn.docs.pages.blocks.fences import (
    _FENCE,
    Fence,
    _id_text,
    _is_closing,
    find_fences,
)
from varde_learn.docs.pages.blocks.lines_check import check_lines
from varde_learn.docs.pages.blocks.spec import AnswerSchema
from varde_learn.docs.pages.blocks.statement import statement_text
from varde_learn.docs.pages.blocks_render import COMPONENTS
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.render import render_page

from .ui_fence import example_fence, toml_props


def fenced(lang: str, body: str, id_: str = "b1", before: str = "") -> str:
    """A `ui` fence holding the statement for a TOML-written body."""
    statement = statement_text(id_, lang, toml_props(body))
    return f"{before}```ui id={id_}\n{statement}\n```\n"


def rules(doc: str) -> list[str]:
    return [e.rule for e in blocks.check(doc)]


def messages(doc: str) -> str:
    return "\n".join(e.message for e in blocks.check(doc))


MODEL = """[[entity]]
name = "a"
key = "id"
fields = { id = "uuid" }
"""


def test_all_types_registered():
    assert blocks.TYPES == (
        "chart",
        "data-model",
        "decision",
        "endpoint",
        "flow",
        "table",
        "ui-states",
        "wireframe",
    )


@pytest.mark.parametrize("name", blocks.TYPES)
def test_each_example_is_valid(name):
    assert blocks.check(example_fence(blocks.SPECS[name].example)) == []


def test_data_model_missing_relation_target():
    body = MODEL + '[[entity.relations]]\nto = "ghost"\nkind = "one-to-one"\n'
    doc = fenced("data-model", body)
    assert rules(doc) == ["relation-target"]
    assert "ghost" in messages(doc)


def test_data_model_missing_key_and_undeclared_key_field():
    no_key = '[[entity]]\nname = "a"\nfields = { id = "uuid" }\n'
    assert "missing-key" in rules(fenced("data-model", no_key))
    bad_key = '[[entity]]\nname = "a"\nkey = "nope"\nfields = { id = "uuid" }\n'
    assert rules(fenced("data-model", bad_key)) == ["entity-key"]


def test_data_model_duplicate_entity():
    assert rules(fenced("data-model", MODEL + MODEL)) == ["entity-duplicate"]


ENDPOINT = 'method = "GET"\npath = "/x"\n[[responses]]\nstatus = 200\n'


def test_endpoint_without_auth_is_an_error():
    doc = fenced("endpoint", ENDPOINT)
    assert rules(doc) == ["endpoint-auth"]
    assert "auth" in messages(doc)


def test_endpoint_explicit_none_accepted():
    assert blocks.check(fenced("endpoint", 'auth = "none"\n' + ENDPOINT)) == []


def test_endpoint_bad_status_method_path():
    body = 'auth = "none"\nmethod = "FETCH"\npath = "x"\n[[responses]]\nstatus = 99\n'
    assert rules(fenced("endpoint", body)) == ["type", "type", "type"]


def test_ui_states_requires_three_states():
    body = '[empty]\nshows = "x"\n'
    doc = fenced("ui-states", body)
    assert rules(doc) == ["ui-state-missing", "ui-state-missing"]
    assert "loading" in messages(doc) and "error" in messages(doc)


def test_ui_states_na_needs_reason_and_exactly_one_form():
    ok = '[empty]\nna = "static page"\n[loading]\nshows = "s"\n[error]\nshows = "e"\n'
    assert blocks.check(fenced("ui-states", ok)) == []
    both = ok.replace('na = "static page"', 'na = "r"\nshows = "x"')
    assert rules(fenced("ui-states", both)) == ["state-form"]
    blank = ok.replace('"static page"', '""')
    assert rules(fenced("ui-states", blank)) == ["type"]


def test_wireframe_region_cross_references_and_width():
    body = 'grid = ["AB", "A"]\n[regions]\nA = "a"\nC = "c"\n'
    assert sorted(rules(fenced("wireframe", body))) == [
        "grid-width",
        "region-undeclared",
        "region-unused",
    ]


def test_flow_unknown_step_and_duplicate_step():
    body = (
        '[[step]]\nid = "a"\ntext = "t"\nnext = ["z"]\n[[step]]\nid = "a"\ntext = "t"\n'
    )
    assert sorted(rules(fenced("flow", body))) == ["step-duplicate", "step-target"]


def test_table_row_width_and_chart_series_length():
    table = 'columns = ["a", "b"]\nrows = [["1"], ["1", "2"]]\n'
    assert rules(fenced("table", table)) == ["row-width"]
    chart = 'kind = "pie"\nlabels = ["x", "y"]\n[[series]]\nname = "s"\nvalues = [1]\n'
    assert sorted(rules(fenced("chart", chart))) == ["series-length", "type"]


def test_unknown_key_is_reported():
    assert rules(fenced("table", 'columns = ["a"]\nrows = [["1"]]\nbogus = 1\n')) == [
        "unknown-key"
    ]


def test_covers_is_reserved_and_validated():
    ok = 'covers = ["order", "post-orders"]\ncolumns = ["a"]\nrows = [["1"]]\n'
    assert blocks.check(fenced("table", ok)) == []
    bad = 'covers = "order"\ncolumns = ["a"]\nrows = [["1"]]\n'
    assert rules(fenced("table", bad)) == ["covers"]


def test_ill_formed_ids():
    body = 'columns = ["a"]\nrows = [["1"]]\n'
    for bad in ("Order", "1a", "a_b", "a" * 49):
        assert "id-invalid" in rules(fenced("table", body, bad)), bad
    assert blocks.check(fenced("table", body, "a" * 48)) == []


def test_duplicate_id_names_first_line():
    body = 'columns = ["a"]\nrows = [["1"]]\n'
    doc = fenced("table", body, "t") + "\n" + fenced("table", body, "t")
    errors = blocks.check(doc)
    assert [e.rule for e in errors] == ["id-duplicate"]
    assert errors[0].line == 9 and "line 2" in errors[0].message


@pytest.mark.parametrize("lang", sorted({*blocks.SPECS, "recap", "deps"}))
def test_old_typed_fence_is_a_removed_error(lang):
    errors = blocks.check(f"```{lang} id=x\nanything\n```\n")
    assert [e.rule for e in errors] == ["toml-fence-removed"]
    assert "varde learn docs blocks" in errors[0].message


def test_indented_fence_and_untyped_fences_are_handled():
    doc = "```python\n```ui id=x\nnot a statement\n```\n"
    assert blocks.check(doc) == []  # a fence inside another fence is text
    ok = '- item\n\n  ```ui id=t\n  t = table(columns: ["a"], rows: [["1"]])\n  ```\n'
    assert blocks.check(ok) == []


def test_help_file_lists_every_type_with_fields_and_example():
    text = files("varde_learn.docs").joinpath("help", "blocks.txt").read_text()
    for name, spec in blocks.SPECS.items():
        assert blocks.type_text(name) in text
        assert spec.example.splitlines()[0].strip() in text
        assert "Fields:" in blocks.type_text(name)


def test_blocks_command_lists_and_describes(capsys):
    assert cli.run(["blocks"]) == 0
    assert "data-model - " in capsys.readouterr().out
    assert cli.run(["blocks", "chart"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("chart - ") and "values" in out
    assert cli.run(["blocks", "nope"]) == 2


@pytest.mark.parametrize("name", ["recap", "deps"])
def test_blocks_command_describes_non_fence_components(name, capsys):
    assert cli.run(["blocks", name]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{name} - ") and f"{name} = {name}(" in out


def test_blocks_check_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text(fenced("endpoint", 'auth = "none"\n' + ENDPOINT))
    assert cli.run(["blocks", "--check", str(good)]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text(
        fenced("endpoint", ENDPOINT, "e")
        + fenced(
            "data-model",
            MODEL + '[[entity.relations]]\nto = "z"\nkind = "one-to-one"\n',
            "m",
        )
        + fenced("table", 'columns = ["a"]\nrows = [["1"]]\n', "m")
    )
    assert cli.run(["blocks", "--check", str(bad)]) == 1
    lines = [
        ln for ln in capsys.readouterr().out.splitlines() if ": warning: " not in ln
    ]
    assert [ln.split(": ")[1] for ln in lines] == [
        "endpoint-auth",
        "relation-target",
        "id-duplicate",
    ]
    assert cli.run(["blocks", "--check", str(tmp_path / "none.md")]) == 2


# --- component registry and line data ---------------------------------------


def _example_data(name):
    (statement,) = parse_lines(blocks.COMPONENT_SPECS[name].example).statements
    return statement.props


@pytest.mark.parametrize("name", sorted(blocks.COMPONENT_SPECS))
def test_lines_example_parses_and_validates(name):
    text = blocks.COMPONENT_SPECS[name].example
    result = parse_lines(text)
    assert result.errors == []
    (statement,) = result.statements
    assert statement.component == name
    assert blocks.check_props(name, statement.props, statement.line) == []
    assert check_lines(text) == []


def test_lines_validation_reports_faults_with_statement_line():
    text = 'a = table(columns: ["x"], rows: [["1", "2"]])\nb = nope(x: 1)\n'
    errors = check_lines(text)
    assert [(e.line, e.rule) for e in errors] == [
        (1, "row-width"),
        (2, "component-unknown"),
    ]


def test_lines_partial_tail_is_not_an_error():
    assert (
        check_lines('a = table(columns: ["x"], rows: [["1"]])\nb = tab', partial=True)
        == []
    )


def test_components_cover_every_spec_with_render_and_example():
    assert set(COMPONENTS) == set(blocks.COMPONENT_SPECS)
    assert {"recap", "deps", "decision", "chart"} <= set(COMPONENTS)
    for name, component in COMPONENTS.items():
        assert component.spec is blocks.COMPONENT_SPECS[name]
        out = component.render(_example_data(name), "id1")
        assert out and "vb-error" not in out


def test_recap_and_deps_render_from_their_props():
    from varde_learn.docs.pages.graph import render_deps
    from varde_learn.docs.pages.recap_block import render_recap

    deps = _example_data("deps")
    assert COMPONENTS["deps"].render(deps, "d") == render_deps(
        {"a": [], "b": ["a"], "c": ["a", "b"]}
    )
    recap = _example_data("recap")
    assert COMPONENTS["recap"].render(recap, "r") == render_recap(recap, "r")


def test_decision_answer_schema_and_render():
    data = _example_data("decision")
    answer_schema = COMPONENTS["decision"].answer_schema
    assert answer_schema is not None
    schema = answer_schema(data)
    assert schema == AnswerSchema(
        "verdict", ("text",), ("approved", "denied", "commented")
    )
    narrowed = answer_schema({**data, "options": ["approve"]})
    assert narrowed is not None and narrowed.allowed == ("approved",)
    assert 'data-item="q"' in COMPONENTS["decision"].render(data, "q")
    answering = {"decision", "choice", "form", "comment", "ranking", "slider"}
    assert all(
        c.answer_schema is None for n, c in COMPONENTS.items() if n not in answering
    )


def test_deps_and_recap_validation():
    assert blocks.check_props("deps", {"edges": {"a": "b"}}, 1)
    assert blocks.check_props("deps", {"edges": {"a:b": []}}, 1)
    assert blocks.check_props("deps", {}, 1)
    assert blocks.check_props("recap", {"rows": [{"file": "a"}]}, 1)
    assert blocks.check_props("recap", {}, 1)


def test_help_shows_line_syntax_for_every_component(capsys):
    assert cli.run(["blocks"]) == 0
    out = capsys.readouterr().out
    for name in blocks.COMPONENT_SPECS:
        assert f"  {name} = {name}(" in out
    assert len([ln for ln in out.splitlines() if re.match(r"^[a-z-]* - ", ln)]) >= 8


def reference_find_fences(text, langs):
    """The scanner as it was before `scan_fences` (pinned for the differential test)."""
    lines = text.expandtabs(4).splitlines()
    found, i = [], 0
    while i < len(lines):
        opening = _FENCE.match(lines[i])
        if opening is None:
            i += 1
            continue
        indent, marker, lang = len(opening.group(1)), opening.group(2), opening.group(3)
        body, j = [], i + 1
        while j < len(lines) and not _is_closing(lines[j], marker):
            body.append(lines[j][min(indent, len(lines[j]) - len(lines[j].lstrip())) :])
            j += 1
        if lang in langs:
            found.append(
                Fence(lang, i + 1, _id_text(opening.group(4)), "\n".join(body))
            )
        i = j + 1
    return found


def test_find_fences_matches_the_reference_scanner():
    import random

    rng = random.Random(7)  # noqa: S311 - test data
    pieces = [
        "```",
        "~~~",
        "````",
        "decision",
        "ui",
        "id=a",
        "  ",
        "\t",
        "x = 1",
        "",
        "text",
        " id=b",
    ]
    for _ in range(3000):
        lines = [
            "".join(rng.choices(pieces, k=rng.randint(0, 4)))
            for _ in range(rng.randint(0, 9))
        ]
        text = rng.choice(["\n", "\r\n"]).join(lines)
        langs = frozenset({"decision", "ui", ""})
        assert find_fences(text, langs) == reference_find_fences(text, langs)


@pytest.mark.parametrize("name", sorted(blocks.COMPONENT_SPECS))
def test_every_component_example_is_one_valid_statement_that_renders(name):
    spec = blocks.COMPONENT_SPECS[name]
    (statement,) = parse_lines(spec.example).statements
    assert statement.id == name and statement.component == name
    doc = example_fence(spec.example)
    # a container's example names ids that other statements of a real page hold
    assert [e for e in blocks.check(doc) if not e.rule.startswith("container-")] == []
    assert "vb-error" not in render_page(doc, "t.md").body


def test_help_file_holds_every_component_text():
    text = files("varde_learn.docs").joinpath("help", "blocks.txt").read_text()
    for name in blocks.COMPONENT_SPECS:
        assert blocks.type_text(name) in text
