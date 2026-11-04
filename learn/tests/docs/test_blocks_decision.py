"""Decision block schema: valid example, bad option, duplicate id, missing question."""

from __future__ import annotations

from varde_learn.docs.pages import blocks

from .ui_fence import example_fence, ui_fence

VALID = 'question = "Ship it?"\n'


def fenced(body: str, id_: str = "d1", before: str = "") -> str:
    return before + ui_fence("decision", body, id_)


def rules(doc: str) -> list[str]:
    return [e.rule for e in blocks.check(doc)]


def test_example_is_valid():
    assert blocks.check(example_fence(blocks.SPECS["decision"].example)) == []


def test_minimal_block_is_valid():
    assert blocks.check(fenced(VALID)) == []


def test_unknown_option():
    assert rules(fenced(VALID + 'options = ["approve", "maybe"]\n')) == [
        "option-unknown"
    ]


def test_duplicate_option():
    assert rules(fenced(VALID + 'options = ["deny", "deny"]\n')) == ["option-duplicate"]


def test_duplicate_id_reports_line():
    doc = fenced(VALID) + fenced(VALID)
    errors = blocks.check(doc)
    assert [e.rule for e in errors] == ["id-duplicate"]
    assert errors[0].line == 7


def test_missing_question():
    assert rules(fenced('options = ["approve"]\n')) == ["missing-key"]


def test_evidence_row_needs_label_and_text():
    body = VALID + '[[evidence]]\nlabel = "a"\n'
    assert rules(fenced(body)) == ["missing-key"]


def test_unknown_key():
    assert rules(fenced(VALID + "extra = 1\n")) == ["unknown-key"]


def test_blocks_command_prints_fields_and_example(capsys):
    text = blocks.type_text("decision")
    assert "question" in text and "options" in text and "evidence" in text
    assert 'question: "' in text
