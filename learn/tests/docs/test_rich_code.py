"""The code panel: lines, ranges, marks, escaping, highlighting that keeps the text,
plain fenced code, the Copy button and the no-JS panel."""

from __future__ import annotations

import html
import re
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks_render.code import (
    ALIASES,
    Panel,
    render_code,
    render_code_panel,
    tokenize,
)
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
SAMPLES = {
    "python": (
        'def f(x):\n    """doc\n    more"""\n    return f"{x}" + \'a\' # c\n0x1F 3.5e2'
    ),
    "js": "const a = `x\ny`; /* c\nd */ // e\nif (a) { return 1_000; } 'un",
    "json": '{"a": [1, 2.5, true, null], "b": "x\\"y"}',
    "shell": "# c\nfor x in 1 2; do echo \"$x\" 'q'; done # t",
}


def panel_html(source: str, language: str = "", **choices: Any) -> str:
    return render_code_panel(source, language, Panel(**choices))


def text_of(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def code_text(markup: str) -> str:
    """The text inside `<code>`: what a reader selects, line numbers excluded."""
    inner = markup.split("<code", 1)[1].split(">", 1)[1].split("</code>", 1)[0]
    return text_of(inner)


@pytest.mark.parametrize("language", sorted(SAMPLES))
def test_highlighting_round_trips_the_source(language: str) -> None:
    source = SAMPLES[language]
    pieces = tokenize(source, language)
    assert "".join(text for _, text in pieces) == source
    assert any(kind for kind, _ in pieces)
    assert code_text(panel_html(source, language)) == source + "\n"


@pytest.mark.parametrize("language", ["", "cobol", "<b>", "markdown"])
def test_unknown_or_missing_language_is_plain(language: str) -> None:
    source = "def f(): return 1  # not coloured"
    assert tokenize(source, language) == [("", source)]
    markup = panel_html(source, language)
    assert 'class="vd-code-k"' not in markup


def test_aliases_name_only_known_families() -> None:
    assert set(ALIASES.values()) == {"python", "js", "json", "shell"}


def test_hostile_text_is_escaped_in_every_slot() -> None:
    hostile = '<script>alert(1)</script> "q" & </pre>'
    markup = render_code(
        {"language": 'py"><img src=x>', "title": hostile, "source": hostile}
    )
    assert "<script>" not in markup and "<img" not in markup
    assert "style=" not in markup
    assert code_text(markup) == hostile + "\n"


def test_big_source_keeps_every_line() -> None:
    source = "\n".join(f"{i} " + "z" * 400 for i in range(600)) + "\n"
    markup = panel_html(source, "python")
    assert markup.count('class="vd-code-line"') == 600
    assert code_text(markup) == source
    assert "vd-code-d3" in markup


def test_lines_range_is_clamped_and_numbers_start_at_from() -> None:
    source = "\n".join(f"l{i}" for i in range(1, 11))
    markup = panel_html(source, window=[4, 6])
    assert re.findall(r'data-line="(\d+)"', markup) == ["4", "5", "6"]
    assert code_text(markup) == "l4\nl5\nl6\n"
    assert 'data-copy="l4\nl5\nl6"' in markup
    late = panel_html(source, window=[8, 99])
    assert re.findall(r'data-line="(\d+)"', late) == ["8", "9", "10"]
    beyond = panel_html(source, window=[50, 60])
    assert re.findall(r'data-line="(\d+)"', beyond) == ["10"]


def test_mark_lines_carry_a_flag_and_a_text_note() -> None:
    source = "\n".join(f"l{i}" for i in range(1, 21))
    markup = panel_html(source, mark=[2, [5, 7], [19, 90]])
    flagged = re.findall(r'data-line="(\d+)" data-mark="1"', markup)
    assert flagged == ["2", "5", "6", "7", "19", "20"]
    assert "Marked lines 2, 5-7, 19-20" in markup
    assert "Marked line 3" in panel_html(source, mark=[3])
    assert "Marked" not in panel_html(source, mark=[99])


def test_marks_note_is_capped_for_many_marks() -> None:
    source = "\n".join("x" for _ in range(500))
    markup = panel_html(source, mark=[[i, i] for i in range(1, 400, 2)])
    assert "and 192 more" in markup


def test_copy_text_is_the_raw_source_without_numbers() -> None:
    markup = panel_html("a <b>\nb", "python", numbers=True)
    assert 'data-copy="a &lt;b&gt;\nb"' in markup
    assert re.search(r"\d", code_text(markup).replace("\n", "")) is None


def test_options_are_classes_not_styles() -> None:
    markup = panel_html("a", wrap=True, numbers=False)
    assert "vd-code-wrap" in markup and "vd-code-nonum" in markup
    assert "style=" not in markup


def test_panel_has_a_text_alternative_and_a_focusable_region() -> None:
    markup = panel_html("a\nb", "python", title="q.py")
    assert "<figcaption" in markup and "q.py" in markup and "python" in markup
    assert (
        'role="region" aria-label="q.py, python, lines 1 to 2" tabindex="0"' in markup
    )
    assert 'class="vb code vd-code-panel' in markup


def test_spec_validates_props() -> None:
    ok: dict[str, object] = {"language": "python", "source": "x"}
    assert check_props("code", ok, 1) == []
    assert check_props("code", {**ok, "lines": [2, 3], "mark": [1, [2, 3]]}, 1) == []
    assert check_props("code", {**ok, "wrap": True, "numbers": False}, 1) == []
    assert check_props("code", {**ok, "covers": ["a"]}, 1) == []
    for bad in (
        {"lines": [3, 2]},
        {"lines": [0, 2]},
        {"lines": [1]},
        {"mark": []},
        {"mark": ["a"]},
        {"mark": [[3, 1]]},
        {"wrap": "yes"},
        {"numbers": 1},
        {"extra": 1},
    ):
        assert check_props("code", {**ok, **bad}, 1), bad
    assert check_props("code", {"source": "x"}, 1)
    assert check_props("code", {"language": "python"}, 1)


def test_registered_and_renders_in_a_page() -> None:
    assert "code" in COMPONENTS
    doc = '```ui\nc = code(language: "py", source: "x = 1\\n", mark: [1])\n```\n'
    assert check(doc) == []
    body = render_page(doc, "t.md").body
    assert "vd-code-k" not in body and 'data-mark="1"' in body
    assert "vb-error" not in body


def test_plain_fenced_code_gets_the_panel() -> None:
    body = render_page("```py\nx = <b>\n```\n\n```\nplain\n```\n", "t.md").body
    assert body.count("vd-code-panel") == 2
    assert "language-py" in body and "x = &lt;b&gt;" in body
    assert "<script" not in render_page("```\n<script>x</script>\n```\n", "t.md").body


def test_fixtures_validate_and_stay_escaped() -> None:
    for name in ("rich-code.md", "rich-code-stress.md"):
        doc = (FIXTURES / name).read_text()
        assert check(doc) == [], name
        body = render_page(doc, "t.md").body
        assert "<img" not in body and "<script>alert" not in body
        assert "style=" not in body and "vb-error" not in body
    assert (
        render_page((FIXTURES / "rich-code.md").read_text(), "t.md").body.count(
            "vd-code-panel"
        )
        == 5
    )


# --- interactions (browser; the lead runs the slow tier) ---


@pytest.fixture(scope="module")
def shared_page(browser_session: Any) -> Any:
    page = browser_session.new_page(viewport={"width": 900, "height": 700})
    page.set_default_timeout(10_000)
    return page


@pytest.fixture
def open_page(tmp_path: Path, shared_page: Any) -> Iterator[Any]:
    doc = tmp_path / "plan.md"
    doc.write_text((FIXTURES / "rich-code.md").read_text(encoding="utf-8"))
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    problems: list[str] = []
    shared_page.on("pageerror", lambda error: problems.append(str(error)))
    shared_page.goto(f"http://127.0.0.1:{server.port}/")
    shared_page.wait_for_selector(".vd-code .vd-code-copy")
    shared_page.wait_for_timeout(600)  # the live refresh rebuilds widgets once
    shared_page.wait_for_selector(".vd-code .vd-code-copy")
    yield shared_page
    assert problems == []
    shared_page.goto("about:blank")
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.mark.slow
def test_interact_copy_writes_the_raw_source_and_announces_it(open_page: Any) -> None:
    page = open_page
    page.evaluate(
        "() => { window.__copied = null; Object.defineProperty(navigator, 'clipboard',"
        " {configurable: true, value: {writeText: (t) => { window.__copied = t;"
        " return Promise.resolve(); }}}); }"
    )
    panel = page.locator(".vd-code").first
    raw = panel.get_attribute("data-copy")
    button = panel.get_by_role("button", name="Copy code")
    assert button.bounding_box()["height"] >= 44
    button.click()
    assert page.evaluate("() => window.__copied") == raw
    assert not re.search(r"^\s*\d+\s", raw or "", re.MULTILINE)
    status = panel.locator(".vd-code-status")
    assert "Copied" in status.inner_text()
    assert status.get_attribute("aria-live") == "polite"


@pytest.mark.slow
def test_interact_keyboard_reaches_the_scroll_region(open_page: Any) -> None:
    page = open_page
    region = page.locator(".vd-code").first.locator(".vd-code-scroll")
    page.locator(".vd-code").first.get_by_role("button", name="Copy code").focus()
    page.keyboard.press("Tab")
    assert region.evaluate("(el) => el === document.activeElement")
    assert region.get_attribute("role") == "region"


def test_without_javascript_the_panel_still_reads(tmp_path: Path) -> None:
    """Served HTML alone carries caption and code; the copy button is JS-only."""
    doc = tmp_path / "plan.md"
    doc.write_text((FIXTURES / "rich-code.md").read_text(encoding="utf-8"))
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/") as reply:
            body = reply.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    assert "vd-code-copy" not in body
    figure = body[body.index('class="vd-code') :]
    assert "queue.py" in figure.split("</figcaption>")[0]
    code = figure.split("<pre")[1].split("</pre>")[0]
    assert "def load" in html.unescape(re.sub(r"<[^>]+>", "", code))
