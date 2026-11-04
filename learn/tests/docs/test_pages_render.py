import re
from pathlib import Path

import pytest
from varde_learn.docs.pages import render
from varde_learn.docs.pages.render import render_inline, render_page

FIXTURES = Path(__file__).parent / "fixtures" / "pages"
GARBAGE = ("&lt;!--", "**", "&lt;div", "\x00", "```", "| ---")


def body_of(markdown: str) -> str:
    return render_page(markdown, "doc.md").body


def fixture_page(name: str) -> render.RenderedPage:
    return render_page((FIXTURES / name).read_text(encoding="utf-8"), name)


@pytest.mark.parametrize("name", ["plan.md", "task.md"])
def test_fixture_renders_without_escaped_garbage(name: str) -> None:
    body = re.sub(r"<code>.*?</code>", "", fixture_page(name).body)
    for needle in GARBAGE:
        assert needle not in body, needle
    assert "<!--" not in body
    assert "<script" not in body


def test_plan_fixture_structure() -> None:
    page = fixture_page("plan.md")
    assert page.status == "type: plan · status: backlog"
    assert '<span class="status">backlog</span>' in page.body
    anchors = [b.anchor for b in page.blocks]
    assert "problem" in anchors and "problem/1" in anchors
    assert len(set(anchors)) == len(anchors)
    assert all(len(b.text) <= 80 for b in page.blocks)


def test_task_fixture_status_and_inline_code() -> None:
    page = fixture_page("task.md")
    assert page.status == "type: task · status: todo · risk: high"
    assert (
        "<code>render_page(markdown, doc_name) -&gt; RenderedPage</code>" in page.body
    )


def test_nested_lists_and_continuation() -> None:
    md = (
        "- one\n  continues here\n  - nested a\n  - nested b\n- two\n\n"
        "1. first\n2. second\n"
    )
    body = body_of(md)
    assert (
        "<li>one continues here<ul><li>nested a</li><li>nested b</li></ul></li>" in body
    )
    assert "<li>two</li>" in body
    assert "<ol><li>first</li><li>second</li></ol>" in body


def test_task_list_hr_quote_and_fence() -> None:
    md = "- [ ] open\n- [x] done\n\n---\n\n> quoted **bold**\n\n```py\nx = <b>\n```\n"
    body = body_of(md)
    assert 'class="task">☐' in body and 'class="task done">☑' in body
    assert "<hr>" in body
    assert "<blockquote><p>quoted <strong>bold</strong></p></blockquote>" in body
    assert '<code class="language-py">' in body and "x = &lt;b&gt;\n</span>" in body


def test_table_with_pipe_in_code() -> None:
    body = body_of("| a | b |\n|---|:-:|\n| `x | y` | 2 |\n")
    assert "<th>a</th>" in body and '<th class="align-center">b</th>' in body
    assert "<td><code>x | y</code></td>" in body


def test_comments_dropped_outside_fences_only() -> None:
    md = (
        "before <!-- gone --> after\n\n<!--\nmulti\nline\n-->\n\n"
        "```\n<!-- kept -->\n```\n"
    )
    body = body_of(md)
    assert "gone" not in body and "multi" not in body
    assert "&lt;!-- kept --&gt;" in body


def test_blocks_registry_used_for_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        render.BLOCKS,
        "deps",
        lambda content, block_id, offset, ctx: f"<p>{len(content.splitlines())}</p>",
    )
    assert "<p>2</p>" in body_of("```deps\na: b\nb:\n```\n")
    monkeypatch.delitem(render.BLOCKS, "deps")
    assert 'class="language-deps"><span' in body_of("```deps\na: b\n```\n")


def test_block_hash_changes_only_for_changed_block() -> None:
    first = render_page("# A\n\none\n\ntwo\n", "d")
    second = render_page("# A\n\none\n\nTWO\n", "d")
    assert [b.hash for b in first.blocks][:2] == [b.hash for b in second.blocks][:2]
    assert first.blocks[2].hash != second.blocks[2].hash
    assert [b.anchor for b in first.blocks] == ["a", "a/1", "a/2"]


def test_duplicate_headings_get_distinct_anchors() -> None:
    page = render_page("# Notes\n\n# Notes\n", "d")
    assert [b.anchor for b in page.blocks] == ["notes", "notes-2"]


HOSTILE = [
    "<script>alert(1)</script>",
    "<svg onload=alert(1)>",
    '<img src=x onerror="alert(1)">',
    '<a href="javascript:alert(1)">x</a>',
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](&#106;avascript:alert(1))",
    "[x](\\u006aavascript:alert(1))",
    "[x](java\tscript:alert(1))",
    "[x](data:text/html;base64,PHNjcmlwdD4=)",
    "[x](vbscript:msgbox)",
    "[x](//evil.example/x)",
    '[x](http://a.example "t\\" onmouseover=\\"alert(1)")',
    '[x](http://a.example "a" onmouseover="alert(1)")',
    "[x][ref]\n\n[ref]: javascript:alert(1)",
    "<div onclick=alert(1)>x</div>",
    "`</code><script>alert(1)</script>`",
    "| <script> |\n|---|\n| <svg onload=1> |",
    "- <script>alert(1)</script>",
    "# <script>alert(1)</script>",
]


@pytest.mark.parametrize("md", HOSTILE)
def test_hostile_input_neutralised(md: str) -> None:
    body = body_of(md)
    lowered = body.lower()
    assert "<script" not in lowered and "<svg" not in lowered
    assert "<img" not in lowered and "<div onclick" not in body
    unquoted = re.sub(r'"[^"]*"', '""', body)
    assert not re.search(r"""<[^>]*\son\w+\s*=""", unquoted)
    assert not re.search(r'href="(?!https?://|#)', body)


def test_link_rules() -> None:
    assert render_inline("[a](https://x.example/p?q=1&r=2)") == (
        '<a href="https://x.example/p?q=1&amp;r=2" rel="noopener noreferrer">a</a>'
    )
    assert (
        render_inline("[a](#sec)") == '<a href="#sec" rel="noopener noreferrer">a</a>'
    )
    assert render_inline("[a](notes/x.md)") == (
        '<span class="relative-link" title="notes/x.md">a</span>'
    )
    assert render_inline("[a](mailto:x@y.z)") == "a"
    assert render_inline("[a][ref]") == "[a][ref]"


def test_titles_with_quotes_stay_inside_attribute() -> None:
    out = render_inline('[a](https://x.example "x\\" onmouseover=\\"y")')
    assert " onmouseover=" not in re.sub(r'title="[^"]*"', "", out)
    out = render_inline('[a](https://x.example "say &quot;hi&quot;")')
    assert out.count('"') % 2 == 0


def test_inline_markers_not_applied_inside_code_or_urls() -> None:
    assert (
        render_inline("`**a**` and **b**")
        == "<code>**a**</code> and <strong>b</strong>"
    )
    out = render_inline("[a](https://x.example/**b**/c)")
    assert 'href="https://x.example/**b**/c"' in out


def test_nul_input_cannot_forge_tokens() -> None:
    assert "\x00" not in render_inline("`a` \x000\x00")


def test_nul_in_table_row_does_not_crash_or_hang() -> None:
    body = body_of("|a|b|\n|-|-|\n|\x005\x00|x|\n|`\x000\x00`|y|\n")
    assert "<table>" in body
    assert "\x00" not in body


def test_deep_quote_nesting_is_bounded() -> None:
    body = body_of(">" * 3000 + " deep")
    assert "deep" in body
    assert body.count("<blockquote>") <= 25


def test_deep_list_nesting_is_bounded() -> None:
    lines = [" " * (2 * n) + "- item" for n in range(1500)]
    body = body_of("\n".join(lines))
    assert "item" in body
    assert body.count("<ul>") <= 25


@pytest.mark.parametrize(
    "text",
    ["*a " * 20000, "_a " * 20000, "**a " * 20000, "[a" * 20000, "[a](x &quot;" * 5000],
)
def test_pathological_inline_is_fast(text: str) -> None:
    import time

    start = time.monotonic()
    render_inline(text)
    assert time.monotonic() - start < 3


def test_duplicate_heading_slugs_stay_unique() -> None:
    page = render_page("# Foo\n\n# Foo\n\n# Foo 2\n\n# Foo\n", "d.md")
    anchors = [b.anchor for b in page.blocks if "/" not in b.anchor]
    assert len(anchors) == len(set(anchors)) == 4
    ids = re.findall(r' id="([^"]+)"', page.body)
    assert len(ids) == len(set(ids))


def test_link_title_has_no_code_markup() -> None:
    out = render_inline('[a](https://x.io "t `c` u")')
    assert 'title="t  u"' in out or "title=" not in out
    assert 'title="t <code>' not in out


def test_comment_marker_in_code_span_keeps_later_content() -> None:
    body = body_of("use `<!--` to open\n\nlater paragraph\n\nx <!-- gone --> y\n")
    assert "later paragraph" in body
    assert "gone" not in body


def test_heading_ids_are_prefixed_and_anchors_unchanged() -> None:
    page = render_page("# Foo\n\ntext\n", "d.md")
    assert ' id="h-foo"' in page.body
    assert [b.anchor for b in page.blocks] == ["foo", "foo/1"]


def test_non_latin_headings_get_distinct_stable_anchors() -> None:
    first = render_page("# \u65e5\u672c\n\n# \u4e2d\u6587\n", "d.md")
    again = render_page("# \u4e2d\u6587\n\n# \u65e5\u672c\n", "d.md")
    anchors = {b.anchor for b in first.blocks}
    assert len(anchors) == 2 and "section" not in anchors
    assert anchors == {b.anchor for b in again.blocks}


def _recording_block(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    def renderer(body, block_id, offset, ctx):
        calls.append((body, block_id, offset, ctx))
        return "<p>typed</p>"

    monkeypatch.setitem(render.BLOCKS, "demo", renderer)
    return calls


def test_info_string_with_and_without_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recording_block(monkeypatch)
    page = render_page("# A\n\n```demo id=m-1 extra\nx\n```\n\n```demo\ny\n```\n", "d")
    assert [c[1] for c in calls] == ["m-1", None]
    assert [b.anchor for b in page.blocks] == ["a", "m-1", "a/2"]


def test_invalid_id_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recording_block(monkeypatch)
    page = render_page("# A\n\n```demo id=Bad_Id\nx\n```\n", "d")
    assert calls[0][1] is None and page.blocks[1].anchor == "a/1"


def test_duplicate_id_gets_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    _recording_block(monkeypatch)
    md = "```demo id=m\nx\n```\n\n```demo id=m\ny\n```\n\n# m\n"
    anchors = [b.anchor for b in render_page(md, "d").blocks]
    assert anchors[:2] == ["m", "m-2"]


def test_id_block_keeps_later_plain_anchors(monkeypatch: pytest.MonkeyPatch) -> None:
    _recording_block(monkeypatch)
    plain = render_page("# A\n\n```demo\nx\n```\n\nafter\n", "d")
    typed = render_page("# A\n\n```demo id=m\nx\n```\n\nafter\n", "d")
    assert plain.blocks[-1].anchor == typed.blocks[-1].anchor == "a/2"
    assert plain.blocks[1].hash != "" and 'data-anchor="m"' in typed.body


def test_renderer_receives_line_offset_and_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recording_block(monkeypatch)
    ctx = render.PageCtx("plan")
    md = "---\ntype: plan\n---\n# A\n\n```demo id=m\nx\n```\n"
    md += "\n- item\n\n  ```demo\n  y\n  ```\n"
    render_page(md, "plan", ctx)
    # body of first fence is document line 7 (1-based); six lines precede it
    assert calls[0][2] == 6 and md.splitlines()[calls[0][2]] == "x"
    assert md.splitlines()[calls[1][2]].strip() == "y"
    assert calls[0][3] is ctx


def test_unregistered_type_with_id_stays_plain_code() -> None:
    page = render_page("# A\n\n```nope id=m\nx\n```\n", "d")
    assert page.blocks[1].anchor == "a/1"


def test_heading_slug_does_not_collide_with_earlier_block_id():
    from varde_learn.docs.pages.render import render_page

    page = render_page("```deps id=order\n```\n\n# Order\n", "d.md")
    anchors = [b.anchor for b in page.blocks]
    assert len(anchors) == len(set(anchors))
