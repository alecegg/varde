# ruff: noqa: S106
import re
from pathlib import Path

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages import serve
from varde_learn.docs.pages.assemble import (
    assemble,
    assemble_page,
    assemble_static,
    drop_pending_tail,
    parse_page_stream,
)
from varde_learn.docs.pages.comments import append_comment

FIXTURE = Path(__file__).parent / "fixtures" / "page-basic.md"


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "page.md"
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_served_page_keeps_the_existing_shell(doc: Path) -> None:
    out = assemble_page(doc, token='t"k')
    assert out.startswith('<!doctype html><html lang="en"><head><meta charset="utf-8">')
    assert '<meta name="varde-token" content="t&quot;k"><title>page.md</title>' in out
    scripts = re.findall(r'<script src="([^"]+)" defer></script>', out)
    assert scripts == [
        f"/static/{n}" for n in ("app.js", "blocks.js", "recap.js", "inputs_ordered.js")
    ]
    assert '<main data-role="page">' in out and out.endswith("</main></body></html>")


def test_render_document_is_the_assembler(doc: Path) -> None:
    assert serve.render_document(doc, "tok") == assemble_page(doc, token="tok")


def test_served_page_includes_comment_threads(doc: Path) -> None:
    append_comment(doc, "basic-page/1", "Some text", "note <x>")
    out = assemble_page(doc, token="tok")
    assert 'class="thread"' in out and "note &lt;x&gt;" in out


def test_source_html_is_escaped(doc: Path) -> None:
    out = assemble_page(doc, token="tok")
    assert "<b>" not in out and "&lt;b&gt;" in out


def test_static_page_has_no_script_token_or_handlers(doc: Path) -> None:
    out = assemble_static(doc)
    assert "<script" not in out and "varde-token" not in out
    assert "onclick=" not in out and "/static/" not in out
    assert "<style>" in out and ".block" in out


def test_static_inputs_are_read_only(doc: Path) -> None:
    out = assemble_static(doc)
    assert "decision-verdict" in out
    assert out.count("<button ") == out.count("<button disabled ") > 0
    assert "<textarea disabled " in out


def test_assemble_exposes_part_map(doc: Path) -> None:
    assert assemble(doc, token="tok").parts == {}


def test_data_part_attributes_pass_through_untouched(doc: Path) -> None:
    from varde_learn.docs.pages.template import make_read_only

    body = '<div class="block" data-part="inc1">x</div>'
    assert make_read_only(body) == body


def test_docs_build_writes_file(doc: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "p.html"
    assert cli.run(["build", str(doc), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == assemble_static(doc)


def test_docs_build_requires_out_and_doc(doc: Path, tmp_path: Path, capsys) -> None:
    assert cli.run(["build", str(doc)]) == 2
    assert "--out <FILE>" in capsys.readouterr().err
    assert (
        cli.run(["build", str(tmp_path / "none.md"), "--out", str(tmp_path / "o.html")])
        == 2
    )


def test_docs_build_reports_unwritable_output(
    doc: Path, tmp_path: Path, capsys
) -> None:
    assert cli.run(["build", str(doc), "--out", str(tmp_path / "no" / "o.html")]) == 2
    assert "cannot write" in capsys.readouterr().err


def test_docs_build_refuses_to_overwrite_its_source(doc: Path, capsys) -> None:
    before = doc.read_text(encoding="utf-8")
    assert cli.run(["build", str(doc), "--out", str(doc)]) == 2
    assert "overwrite the source" in capsys.readouterr().err
    assert doc.read_text(encoding="utf-8") == before


def test_served_page_matches_golden_from_before_the_assembler(tmp_path: Path) -> None:
    # fixtures/page-basic.served.html was rendered by render_document at 2049399c5
    page = tmp_path / "page-basic.md"
    page.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    golden = FIXTURE.with_name("page-basic.served.html").read_text(encoding="utf-8")
    assert assemble_page(page, token="golden-token") == golden


def _page(newline: str) -> str:
    lines = [
        "# T",
        "",
        "```ui",
        "a = flow()",
        'b = table(s: "x",',
        "  rows: [1,",
        "  2])",
        "c = flow()",
        "```",
        "",
        "tail text",
    ]
    return newline.join(lines) + newline


def _ids(text: str) -> list[str]:
    return [b.anchor for b in parse_page_stream(text, "p.md").blocks]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_partial_every_cut_offset_never_raises_and_blocks_are_a_prefix(
    newline: str,
) -> None:
    text = _page(newline)
    full = _ids(text)
    # a cut inside the opener is a stray paragraph, not a block prefix
    start = text.index("```ui") + len("```ui")
    for cut in range(start, len(text) + 1):
        ids = _ids(text[:cut])
        assert ids == full[: len(ids)], cut
        assert drop_pending_tail(text[:cut]) is not None
    assert drop_pending_tail(text) == text


def test_partial_page_drops_unfinished_ui_statement() -> None:
    text = '# T\n\n```ui\na = flow()\nb = table(rows: [1, 2,\n  "x'
    assert drop_pending_tail(text) == "# T\n\n```ui\na = flow()\n```\n"
    body = parse_page_stream(text, "p.md").body
    assert "table" not in body and "rows" not in body


@pytest.mark.parametrize(
    "text",
    [
        "```ui\na = flow()\n```\ntext",
        "plain text",
        "~~~md\n```ui\na = f(\n",  # ui fence nested in a longer outer fence
        "````md\n```ui\na = f(\n",
    ],
)
def test_partial_text_without_open_ui_fence_is_unchanged(text: str) -> None:
    assert drop_pending_tail(text) == text


@pytest.mark.parametrize("opener", ["~~~ui", "  ```ui", "```ui"])
def test_partial_other_fence_forms(opener: str) -> None:
    fence = opener.strip()[:3]
    text = f"{opener}\na = flow()\nb = t(rows: [1,\n"
    assert drop_pending_tail(text) == f"{opener}\na = flow()\n{fence}\n"


def test_partial_cut_at_opener_without_newline_is_dropped_cleanly() -> None:
    assert drop_pending_tail("```ui") == "```ui"
    assert "```ui```" not in drop_pending_tail("# T\n```ui")
