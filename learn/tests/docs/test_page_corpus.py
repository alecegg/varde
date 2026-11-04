"""Eval corpus (notes/ev-baseline.md): each item is a script-free component page."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from varde_learn.docs.pages import cli as pages_cli

CORPUS = Path(__file__).parent / "fixtures" / "corpus"
# ev-baseline "Corpus": 1 stored doc + 0 exported pages + 10 eval cases.
BASELINE_TOTAL = 11
SCRIPT_OR_HTML = re.compile(
    r"<\s*(script|style|iframe)\b|^```\s*custom", re.IGNORECASE | re.MULTILINE
)


def fixtures() -> list[Path]:
    return sorted(CORPUS.glob("*.md"))


def is_met(doc: Path, capsys: pytest.CaptureFixture[str]) -> bool:
    text = doc.read_text()
    if SCRIPT_OR_HTML.search(text) or "```ui" not in text:
        return False
    exit_code = pages_cli.check_blocks(doc)
    return exit_code == 0 and ": error:" not in capsys.readouterr().out


def test_every_fixture_passes_check_with_no_script(
    capsys: pytest.CaptureFixture[str],
) -> None:
    unmet = [doc.name for doc in fixtures() if not is_met(doc, capsys)]
    assert unmet == []


def test_corpus_is_met_at_ninety_percent(capsys: pytest.CaptureFixture[str]) -> None:
    docs = fixtures()
    total = len(docs)
    met = sum(is_met(doc, capsys) for doc in docs)
    assert total == BASELINE_TOTAL
    assert met * 10 >= total * 9, f"{met} of {total}"
