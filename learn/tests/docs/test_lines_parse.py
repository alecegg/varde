"""Line syntax parser: valid cases, every error class, partial input."""

import pytest
from varde_learn.docs.pages.lines import Ref, parse_lines
from varde_learn.docs.pages.lines.grammar import EXAMPLES


@pytest.mark.parametrize("example", EXAMPLES)
def test_pinned_examples_parse(example):
    result = parse_lines(example)
    assert result.errors == []
    assert result.statements


def test_values_of_every_type():
    text = (
        'a = chart(s: "x\\ny", i: 3, f: -1.5, e: 1e2, t: true, n: null,'
        ' arr: [1, [2]], obj: {"k": {bare: false}})'
    )
    (stmt,) = parse_lines(text).statements
    assert (stmt.id, stmt.component, stmt.line) == ("a", "chart", 1)
    assert stmt.props == {
        "s": "x\ny",
        "i": 3,
        "f": -1.5,
        "e": 100.0,
        "t": True,
        "n": None,
        "arr": [1, [2]],
        "obj": {"k": {"bare": False}},
    }
    assert isinstance(stmt.props["i"], int)


def test_reference_and_multiline_and_comments():
    text = (
        "# top\n"
        "a = flow(x: 1)  # trailing\n"
        "\n"
        "b = table(\n"
        "  src: a,   # ref\n"
        "  rows: [\n"
        "    1,\n"
        "    2,\n"
        "  ],\n"
        ")\n"
    )
    result = parse_lines(text)
    assert result.errors == []
    a, b = result.statements
    assert (a.line, a.end_line, b.line, b.end_line) == (2, 2, 4, 10)
    assert b.props == {"src": Ref("a"), "rows": [1, 2]}


def test_unicode_and_hash_inside_string():
    (stmt,) = parse_lines('a = recap(t: "héllo # 日本 \\u00e9")').statements
    assert stmt.props["t"] == "héllo # 日本 é"


def test_deep_nesting_within_limit():
    text = "a = flow(x: " + "[" * 20 + "]" * 20 + ")"
    assert parse_lines(text).errors == []


def test_empty_and_comment_only():
    assert parse_lines("").statements == []
    assert parse_lines("# only\n\n").errors == []


@pytest.mark.parametrize(
    ("text", "rule", "line"),
    [
        ("A = flow()", "id-invalid", 1),
        ("a = flow()\nb = flow()\na = flow()", "id-duplicate", 3),
        ("\n\na = flow(x: 1, x: 2)", "prop-duplicate", 3),
        ('a = flow(o: {"k": 1, "k": 2})', "prop-duplicate", 1),
        ("a = flow(x: b)", "ref-unknown", 1),
        ("a = flow(x: a)", "ref-unknown", 1),
        ("a = flow()  junk", "trailing", 1),
        ("a flow()", "syntax", 1),
        ("a = (x: 1)", "syntax", 1),
        ("a = flow x", "syntax", 1),
        ("a = flow(x 1)", "syntax", 1),
        ("a = flow(\n  x: 1\n  y: 2\n)", "syntax", 3),
        ("a = flow(x: 01)", "syntax", 1),
        ("a = flow(x: -)", "syntax", 1),
        ("a = flow(x: [1 2])", "syntax", 1),
        ('a = flow(x: "bad \\q")', "syntax", 1),
        ('a = flow(\n  x: "open\n)', "unterminated", 2),
        ("a = flow(x: 1", "unterminated", 1),
        ("ok = flow()\n\nb = flow(x: [", "unterminated", 3),
        ("a = flow(x: " + "[" * 40 + "]" * 40 + ")", "depth", 1),
    ],
)
def test_error_classes_have_lines(text, rule, line):
    result = parse_lines(text)
    assert (result.errors[0].rule, result.errors[0].line) == (rule, line), result.errors


def test_error_text_and_recovery():
    text = "a = flow(x: )\nb = flow(y: 2)\nc = flow(z: ]\nd = flow()"
    result = parse_lines(text)
    assert [e.line for e in result.errors] == [1, 3]
    assert [s.id for s in result.statements] == ["b", "d"]
    assert result.errors[0].text().startswith("line 1: syntax: ")


def test_partial_tail_is_pending_not_error():
    text = "a = flow(x: 1)\nb = table(rows: [1, 2,"
    result = parse_lines(text, partial=True)
    assert result.errors == []
    assert [s.id for s in result.statements] == ["a"]
    assert result.pending == "b = table(rows: [1, 2,"
    assert parse_lines(text).errors[0].rule == "unterminated"


def test_partial_still_reports_real_errors():
    result = parse_lines("A = flow()\nb = fl", partial=True)
    assert result.errors[0].rule == "id-invalid"
    assert result.pending == "b = fl"


def test_partial_complete_text_has_no_pending():
    assert parse_lines("a = flow()\n", partial=True).pending == ""


def test_no_dynamic_evaluation():
    result = parse_lines('a = flow(x: __import__("os"))')
    assert [e.rule for e in result.errors] == ["syntax"]
    assert result.statements == []


def test_huge_integer_is_an_error_not_a_crash():
    result = parse_lines("a = flow(x: " + "9" * 5000 + ")")
    assert result.errors[0].rule == "syntax"
    assert "too many digits" in result.errors[0].message
    assert result.errors[0].line == 1


@pytest.mark.parametrize(
    "tail",
    ["tru", "b", "1.", "1e", "1e+", "-", '"abc', '"ab\\', "[1, tr"],
)
def test_partial_mid_token_cutoff_is_pending(tail):
    text = f"b = flow()\na = table(x: {tail}"
    result = parse_lines(text, partial=True)
    assert result.errors == []
    assert [s.id for s in result.statements] == ["b"]
    assert result.pending == f"a = table(x: {tail}"


@pytest.mark.parametrize("tail", ["a", "a ", "a =", "a = ", "a = fl", "a = flow"])
def test_partial_cutoff_before_open_paren_is_pending(tail):
    result = parse_lines(tail, partial=True)
    assert result.errors == []
    assert result.pending == tail


def test_missing_close_paren_does_not_swallow_next_statement():
    result = parse_lines("a = flow(x: 1\nb = flow()\nc = flow()")
    assert [(e.rule, e.line) for e in result.errors] == [("unterminated", 1)]
    assert [s.id for s in result.statements] == ["b", "c"]


def test_missing_close_paren_after_comma_and_value_forms():
    result = parse_lines('a = flow(x: [1],\n  y: "s"\nb = flow()')
    assert [(e.rule, e.line) for e in result.errors] == [("unterminated", 1)]
    assert [s.id for s in result.statements] == ["b"]


def test_hyphenated_component_names_and_refs():
    text = "my-model = data-model(a: 1)\nscreens = ui-states(of: my-model)"
    result = parse_lines(text)
    assert result.errors == []
    assert [s.component for s in result.statements] == ["data-model", "ui-states"]
    assert result.statements[1].props == {"of": Ref("my-model")}


def test_non_finite_number_rejected():
    assert parse_lines("a = flow(x: 1e999)").errors[0].rule == "syntax"


def test_lone_surrogate_rejected():
    assert parse_lines('a = flow(x: "\\ud800")').errors[0].rule == "syntax"


def test_raw_tab_in_string_has_clear_message():
    (error,) = parse_lines('a = flow(x: "a\tb")').errors
    assert "control character" in error.message
    assert "escape sequence" not in error.message


@pytest.mark.parametrize("literal", ["true", "false", "null"])
def test_literal_words_are_not_valid_ids(literal):
    result = parse_lines(f"{literal} = flow()")
    assert (result.errors[0].rule, result.errors[0].line) == ("id-invalid", 1)
    assert result.statements == []
