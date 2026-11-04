"""Page header strip: chip, plan, commit, links, reading time, escaping."""

from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.docs.pages.header import (
    count_words,
    header_html,
    parse_links,
    reading_minutes,
    status_tone,
)
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"


def _header(front: str, body: str = "# T\n\ntext\n", name: str = "p.md") -> str:
    page = render_page(f"---\n{front}\n---\n\n{body}" if front else body, name).body
    return page[: page.index("</header>")]


@pytest.mark.parametrize(
    ("status", "tone", "glyph"),
    [
        ("todo", "decision", "○"),
        ("in-progress", "info", "◐"),
        ("review", "warning", "▲"),
        ("blocked", "risk", "✕"),
        ("DONE", "success", "✓"),
        ("mystery", "neutral", "•"),
    ],
)
def test_chip_glyph_word_and_tone(status: str, tone: str, glyph: str) -> None:
    assert status_tone(status) == (tone, glyph)
    head = _header(f"status: {status}")
    assert f"vd-hdr-chip vd-hdr-{tone}" in head
    assert f'aria-hidden="true">{glyph}</span>' in head
    assert f'<span class="status">{status}</span>' in head


def test_missing_keys_keep_todays_header() -> None:
    head = _header("type: task\nrisk: high")
    assert '<p class="status">type: task · risk: high</p>' in head
    assert "vd-hdr" not in head
    plain = render_page("# T\n", "p.md")
    assert plain.body.count('class="doc-header"') == 1
    assert 'class="status"' not in plain.body


def test_status_string_is_unchanged() -> None:
    page = render_page("---\ntype: task\nstatus: done\n---\n\n# T\n", "p.md")
    assert page.status == "type: task · status: done"


def test_plan_defaults_to_doc_name_and_key_wins() -> None:
    assert ">p.md</span>" in _header("status: done")
    assert ">my-plan</span>" in _header("status: done\nplan: my-plan")


def test_commit_is_shortened_with_full_value_in_title() -> None:
    sha = "4739f6f54748f4d62a2d95a1e22c8486a3f21080"
    head = _header(f"commit: {sha}")
    assert f'title="{sha}">4739f6f54</span>' in head


def test_link_filter_drops_unsafe_entries() -> None:
    links = parse_links(
        "javascript:alert(1), /etc/passwd, ../x.md, a.md, sub/b.md, "
        "http://ok.example/p, ftp://x.example/f, https://bad host/x, data:text/html,x"
    )
    assert [href for href, _ in links] == ["a.md", "sub/b.md", "http://ok.example/p"]
    head = _header("links: javascript:alert(1), a.md")
    assert "javascript" not in head
    assert 'href="a.md" rel="noopener"' in head


def test_links_are_capped_and_long_labels_shortened() -> None:
    many = ", ".join(f"p{n}.md" for n in range(20))
    assert len(parse_links(many)) == 8
    ((_, label),) = parse_links("https://example.com/" + "a" * 100)
    assert len(label) <= 40


def test_hostile_text_is_escaped() -> None:
    head = _header(
        'status: <script>x</script>\nplan: <b>"p"</b>\ncommit: <img src=x onerror=y>\n'
        "risk: <i>hi</i>",
        name="<n>.md",
    )
    assert "<script" not in head and "<b>" not in head and "<img" not in head
    assert "<i>" not in head and "&lt;script&gt;" in head
    assert "style=" not in head


@pytest.mark.parametrize(
    ("words", "minutes"), [(0, 1), (1, 1), (200, 1), (201, 2), (400, 2), (401, 3)]
)
def test_reading_time_boundaries(words: int, minutes: int) -> None:
    assert reading_minutes(words) == minutes


def test_word_count_skips_fences_and_counts_tables() -> None:
    lines = [
        "# Title here",
        "",
        "Some prose words.",
        "```ui",
        "a = stats(x: 1)",
        "```",
        "| a | b |",
        "| --- | --- |",
        "| one | two |",
    ]
    assert count_words(lines) == 2 + 3 + 2 + 2


def test_reading_time_shown_in_strip() -> None:
    body = "# T\n\n" + "word " * 450
    assert ">3 min<" in _header("status: done", body)
    assert ">1 min<" in _header("status: done")


def test_header_html_is_pure_and_closed() -> None:
    out = header_html({"status": "done"}, "n", 10)
    assert out.startswith('<header class="doc-header"><p class="doc-name">n</p>')
    assert out.endswith("</header>")


def test_fixtures_render_strip() -> None:
    for name in ("page-header.md", "page-header-stress.md"):
        body = render_page((FIXTURES / name).read_text(), name).body
        assert 'class="vd-hdr"' in body
        assert "<script" not in body and "<img" not in body and "<style" not in body


def test_iso_dates_are_wrapped_so_they_cannot_split_at_a_hyphen() -> None:
    head = _header("status: todo\nstatus_at: 2026-11-04T09:15 note")
    assert 'status_at: <span class="vd-date">2026-11-04</span>T09:15 note' in head
    css = (
        Path(__file__).parents[2]
        / "src/varde_learn/docs/pages/static/css/50-blocks.css"
    ).read_text()
    assert ".vd-date { white-space: nowrap; }" in css
