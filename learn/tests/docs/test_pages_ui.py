"""Served `ui` fences: anchors, error cards, streaming, includes and the answer path."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages.assemble import assemble, parse_page_stream
from varde_learn.docs.pages.blocks import check
from varde_learn.docs.pages.comments import fold, read_rows
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.serve import PageServer

MIGRATE = Path(__file__).parent / "fixtures" / "migrate"
OLD_IDS = ["pick", "opts", "graph", "rc"]


def test_converted_fixture_keeps_data_anchor_equal_to_the_old_id() -> None:
    converted = (MIGRATE / "converted.md").read_text()
    page = render_page(converted, "page.md")
    anchors = [b.anchor for b in page.blocks]
    for old_id in OLD_IDS:
        assert old_id in anchors
        assert f'data-anchor="{old_id}"' in page.body
    assert "vb-error" not in page.body and "toml-fence-removed" not in page.body


def test_converted_fixture_passes_learn_check_and_the_old_one_is_removed() -> None:
    assert check((MIGRATE / "converted.md").read_text()) == []
    errors = check((MIGRATE / "old.md").read_text())
    assert {e.rule for e in errors} == {"toml-fence-removed"}
    assert len(errors) == len(OLD_IDS)
    assert all("varde learn docs blocks" in e.message for e in errors)


def test_a_statement_per_anchor_with_its_own_line_span() -> None:
    text = '# T\n\n```ui\na = table(columns: ["x"], rows: [["1"]])\nb = flow()\n```\n'
    page = render_page(text, "p.md")
    spans = {b.anchor: (b.start, b.end) for b in page.blocks}
    assert spans["a"] == (3, 4) and spans["b"][0] == 4


def test_a_bad_statement_is_an_error_card_and_the_rest_still_render() -> None:
    text = (
        "```ui\n"
        'ok = table(columns: ["x"], rows: [["1"]])\n'
        'bad = table(columns: ["x"], rows: [["1", "2"]])\n'
        "```\n"
    )
    body = render_page(text, "p.md").body
    assert body.count("vb-error") == 1 and "row-width" in body
    assert 'data-anchor="ok"' in body and 'data-anchor="bad"' in body


def test_a_syntax_error_is_one_error_card_with_the_document_line() -> None:
    body = render_page("# T\n\n```ui\nx = table(columns:\n```\n", "p.md").body
    assert "ui block has" in body and "line 4" in body


def test_streaming_page_drops_the_unfinished_statement() -> None:
    text = '```ui\na = table(columns: ["x"], rows: [["1"]])\nb = table(rows: [[1,'
    body = parse_page_stream(text, "p.md").body
    assert 'data-anchor="a"' in body and "b = table" not in body
    assert "vb-error" not in body


def test_unclosed_fence_with_complete_statements_renders_them() -> None:
    body = parse_page_stream("```ui\na = flow()\n", "p.md").body
    assert 'data-anchor="a"' in body


def test_duplicate_statement_ids_across_fences_get_distinct_anchors() -> None:
    fence = '```ui\na = table(columns: ["x"], rows: [["1"]])\n```\n'
    anchors = [b.anchor for b in render_page(fence + "\n" + fence, "p.md").blocks]
    assert anchors == ["a", "a-2"]


def test_check_reports_a_cross_fence_duplicate_id() -> None:
    fence = '```ui\na = table(columns: ["x"], rows: [["1"]])\n```\n'
    assert [e.rule for e in check(fence + "\n" + fence)] == ["id-duplicate"]


def test_include_parts_are_rendered_into_the_served_page(tmp_path: Path) -> None:
    (tmp_path / "src.md").write_text("## Part\n\nPart text.\n", encoding="utf-8")
    doc = tmp_path / "page.md"
    doc.write_text(
        "# T\n\n```ui\n"
        'inc = include(source: "src.md", select: "heading:part", title: "Part")\n'
        "```\n",
        encoding="utf-8",
    )
    result = assemble(doc, token="t")  # noqa: S106
    assert 'data-part="inc"' in result.html and "Part text." in result.html
    assert result.parts == {"inc": (tmp_path / "src.md").resolve()}
    assert "part-pending" not in result.html


def test_include_failure_is_an_error_card(tmp_path: Path) -> None:
    doc = tmp_path / "page.md"
    doc.write_text(
        '```ui\ninc = include(source: "missing.md", select: "frontmatter")\n```\n',
        encoding="utf-8",
    )
    html = assemble(doc, token="t").html  # noqa: S106
    assert "vb-error" in html and "not found" in html


# --- the widgets through the served page and the answer path -----------------

DOC = (
    "# Plan\n\nBody.\n\n```ui\n"
    'pick = choice(question: "Which?", options: ["a", {"label": "B", "value": "b"}])\n'
    'order = ranking(question: "Urgency?", items: ["a", "b", "c"])\n'
    'conf = slider(label: "Confidence", min: 0, max: 10, step: 2)\n'
    'setup = form(fields: [{"name": "owner", "label": "Owner", "type": "text"}])\n'
    'note = comment(label: "Anything?")\n'
    'ship = decision(question: "Ship?", options: ["approve", "deny"])\n'
    "```\n"
)


@pytest.fixture
def site(tmp_path: Path) -> Iterator[tuple[PageServer, Path]]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, doc
    server.shutdown()
    server.server_close()
    thread.join(5)


def _request(
    server: PageServer, method: str, path: str, body: Any = None
) -> tuple[int, bytes]:
    host = f"127.0.0.1:{server.port}"
    headers = {"Host": host}
    if method == "POST":
        headers |= {
            "Origin": f"http://{host}",
            "Content-Type": "application/json",
            "X-Varde-Token": server.token,
        }
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request(method, path, json.dumps(body) if body else None, headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def _answer(item: str, value: object, text: str = "") -> dict[str, Any]:
    return {
        "anchor": item,
        "kind": "answer",
        "item": item,
        "value": value,
        "text": text,
    }


def test_every_widget_is_in_the_served_page_with_its_statement_id_as_anchor(
    site: tuple[PageServer, Path],
) -> None:
    server, _ = site
    status, data = _request(server, "GET", "/")
    page = data.decode()
    assert status == 200
    for item, marker in [
        ("pick", 'data-component="choice"'),
        ("order", 'data-component="ranking"'),
        ("conf", 'data-component="slider"'),
        ("setup", 'data-component="form"'),
        ("note", 'data-component="comment"'),
        ("ship", "decision-verdict"),
    ]:
        assert f'data-anchor="{item}"' in page, item
        assert re.search(rf'data-item="{item}"', page), item
        assert marker in page, item


@pytest.mark.parametrize(
    ("item", "value", "text"),
    [
        ("pick", "b", ""),
        ("order", ["c", "a", "b"], ""),
        ("conf", 6, ""),
        ("setup", {"owner": "ann"}, ""),
        ("note", "commented", "fine"),
        ("ship", "approved", ""),
    ],
)
def test_each_widget_answer_is_stored_through_the_served_page(
    site: tuple[PageServer, Path], item: str, value: object, text: str
) -> None:
    server, doc = site
    status, _ = _request(server, "POST", "/comments", _answer(item, value, text))
    assert status == 201
    rows = [r for r in fold(read_rows(doc)) if r.get("kind") == "answer"]
    assert [(r["item"], r["value"]) for r in rows] == [(item, value)]


@pytest.mark.parametrize(
    ("item", "value"),
    [("pick", "zzz"), ("order", ["a", "b"]), ("conf", 7), ("setup", {"owner": 3})],
)
def test_a_bad_widget_answer_is_refused_and_stores_nothing(
    site: tuple[PageServer, Path], item: str, value: object
) -> None:
    server, doc = site
    status, _ = _request(server, "POST", "/comments", _answer(item, value))
    assert status == 400
    assert not [r for r in fold(read_rows(doc)) if r.get("kind") == "answer"]


# --- review fixes: error-card span, include parity, id wins over heading slug --


def test_error_card_carries_the_fence_span_and_cannot_touch_other_text(
    tmp_path: Path,
) -> None:
    from varde_learn.docs.pages import edit

    fence = [
        "```ui\n",
        'ok = table(columns: ["x"], rows: [["1"]])\n',
        "x = table(\n",
        "```\n",
    ]
    doc = tmp_path / "p.md"
    doc.write_text("# T\n\nbefore\n\n" + "".join(fence) + "\nafter\n", encoding="utf-8")
    blocks = render_page(doc.read_text(), "p.md").blocks
    assert all(b.end > b.start for b in blocks)
    card = next(b for b in blocks if b.start == 4 and b.end == 8)
    source = edit.read_block(doc, card.anchor).source
    assert source == "".join(fence).rstrip("\n")
    lines = doc.read_text().splitlines(keepends=True)
    out = edit.spliced(lines, card, "REPLACED")
    assert out.startswith("# T\n\nbefore\n\nREPLACED\n") and out.endswith("\nafter\n")
    assert out.count("before") == 1 and out.count("after") == 1


def test_served_and_edit_anchors_agree_after_an_include(tmp_path: Path) -> None:
    (tmp_path / "src.md").write_text("# S\n\npart text\n", encoding="utf-8")
    doc = tmp_path / "page.md"
    doc.write_text(
        "# T\n\nfirst\n\n```ui\n"
        'inc = include(source: "src.md", select: "heading:s")\n'
        "```\n\nsecond\n\nthird\n",
        encoding="utf-8",
    )
    from varde_learn.docs.pages.assemble import include_ctx, read_markdown

    text = read_markdown(doc)
    served = [
        b.anchor for b in render_page(text, doc.name, include_ctx(text, doc)[0]).blocks
    ]
    edit_path = [b.anchor for b in render_page(text, doc.name).blocks]
    served_tail = served[served.index("t/3") :]
    assert served_tail == [a for a in edit_path if a.startswith("t/") and a >= "t/3"]
    assert "t/3" in served and "t/4" in served


def test_statement_id_wins_over_a_colliding_heading_slug() -> None:
    text = '## pick\n\n```ui\npick = decision(question: "Ship?", options: ["a"])\n```\n'
    blocks = render_page(text, "p.md").blocks
    anchors = [b.anchor for b in blocks]
    assert "pick" in anchors and "pick-2" in anchors
    heading = next(b for b in blocks if b.start == 0)
    assert heading.anchor == "pick-2"
