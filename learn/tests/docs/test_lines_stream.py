"""Streaming: complete-statement prefix is stable at every cut offset."""

import pytest
from varde_learn.docs.pages.lines import parse_lines
from varde_learn.docs.pages.lines.grammar import EXAMPLES


def _stream(text):
    return parse_lines(text, partial=True)


PAGE = (
    'model = data-model(name: "User", note: "a \\"q\\" # not a comment")\n'
    "states = ui-states(of: model)  # trailing\n"
    "# comment line\n"
    "speed = slider(min: 0, max: 1.5, step: 0.5, value: -1e2)\n"
    'pick = choice(\n  question: "Which?",\n  options: ["x", "y"],  # why\n'
    '  multi: false,\n  extra: {"k": null, v: [1, 2.5, true]},\n)\n'
    "note = comment(target: pick, text: null)\n"
    'plan-deps = deps(edges: {"b": ["a"], "c": ["a", "b"]})\n'
)


def _ids(statements):
    return [s.id for s in statements]


def test_every_offset_is_prefix_stable_and_never_raises():
    full = parse_lines(PAGE)
    assert full.errors == []
    previous: list = []
    for cut in range(len(PAGE) + 1):
        result = _stream(PAGE[:cut])
        assert result.errors == [], (cut, PAGE[:cut][-30:])
        assert result.statements == full.statements[: len(result.statements)], cut
        assert len(result.statements) >= len(previous), cut  # never shrinks
        previous = result.statements
    assert previous == full.statements


@pytest.mark.parametrize("example", EXAMPLES)
def test_example_cut_at_every_offset(example):
    full = parse_lines(example).statements
    for cut in range(len(example) + 1):
        result = _stream(example[:cut])
        assert result.errors == [], (cut, example[:cut])
        assert result.statements == full[: len(result.statements)]


def test_pending_holds_cut_tail_and_renders_nothing():
    text = 'a = flow()\nb = table(rows: [1, 2,\n  "x'
    result = _stream(text)
    assert _ids(result.statements) == ["a"]
    assert result.pending == 'b = table(rows: [1, 2,\n  "x'
    assert result.errors == []
    assert _ids(_stream(text).statements) == ["a"]


def test_cut_reference_is_pending_not_error():
    text = "a = flow()\nb = states(of: a"
    result = _stream(text)
    assert _ids(result.statements) == ["a"]
    assert result.pending == "b = states(of: a"
    assert result.errors == []


def test_complete_text_has_no_pending():
    result = _stream("a = flow()\n")
    assert result.pending == ""
    assert _ids(result.statements) == ["a"]


def test_real_errors_still_reported_while_streaming():
    result = _stream("a = flow()\nb = x(t: nope)\nc = fl")
    assert [e.rule for e in result.errors] == ["ref-unknown"]
    assert _ids(result.statements) == ["a"]
    assert result.pending == "c = fl"


def test_strict_mode_still_errors_on_cut_tail():
    result = parse_lines("a = flow()\nb = table(rows: [1,")
    assert _ids(result.statements) == ["a"]
    assert [e.rule for e in result.errors] == ["unterminated"]
    assert result.pending == ""
