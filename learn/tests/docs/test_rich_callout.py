"""The callout component: tones, label text, escaping, Copy text, registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.callout import copy_text, render_callout
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.render import render_page

TONES = {
    "info": "Info",
    "decision": "Decision",
    "risk": "Risk",
    "warning": "Warning",
    "success": "Success",
}
FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


@pytest.mark.parametrize(("tone", "word"), TONES.items())
def test_each_tone_has_a_glyph_and_its_word(tone: str, word: str) -> None:
    html = render_callout({"tone": tone, "text": "Body"})
    assert f"vd-callout-{tone}" in html
    assert 'class="vd-callout-glyph" aria-hidden="true"' in html
    assert f"</span> {word}</p>" in html


def test_hostile_text_is_escaped_and_code_spans_render() -> None:
    html = render_callout(
        {"tone": "risk", "title": "<b>t</b>", "text": "<script>x</script> `<i>c</i>`"}
    )
    assert "<script>" not in html and "<b>t</b>" not in html
    assert "&lt;script&gt;" in html and "<code>&lt;i&gt;c&lt;/i&gt;</code>" in html
    assert "style=" not in html


def test_copy_text_is_title_then_text() -> None:
    data: dict[str, object] = {"tone": "info", "title": "T", "text": "Body"}
    assert copy_text(data) == "T\nBody"
    assert 'data-copy="T\nBody"' in render_callout(data)
    assert copy_text({"tone": "info", "text": "Body"}) == "Body"


def test_blank_line_starts_a_paragraph() -> None:
    html = render_callout({"tone": "info", "text": "a\n\nb"})
    assert html.count('class="vd-callout-text"') == 2


def test_spec_rejects_bad_props_and_accepts_covers() -> None:
    assert check_props("callout", {"tone": "info", "text": "x"}, 1) == []
    assert (
        check_props("callout", {"tone": "info", "text": "x", "covers": ["a"]}, 1) == []
    )
    assert check_props("callout", {"tone": "loud", "text": "x"}, 1)
    assert check_props("callout", {"tone": "info"}, 1)
    assert check_props("callout", {"tone": "info", "text": "x", "extra": 1}, 1)


def test_registered_and_renders_through_the_page() -> None:
    assert "callout" in COMPONENTS
    doc = (FIXTURES / "rich-callout.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert body.count("vd-callout-") >= 5 * 3
    assert "vb-error" not in body


def test_stress_fixture_validates_and_stays_escaped() -> None:
    doc = (FIXTURES / "rich-callout-stress.md").read_text()
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "<img" not in body and "<script>alert" not in body
    assert "style=" not in body
