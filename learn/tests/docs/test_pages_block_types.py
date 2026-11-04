import re
from pathlib import Path

import pytest
from varde_learn.docs.pages.actions import component_block_type
from varde_learn.docs.pages.render import render_page

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
DOC = """# Title

Some prose.

- one
- two

| a | b |
| - | - |
| 1 | 2 |

```py
x = 1
```

```ui
pick = choice(question: "Which?", options: ["a", "b"])
ship = decision(question: "Ship?", options: ["approve"])
c = chart(type: "bar", labels: ["x"], series: [{"name": "s", "values": [1]}])
bad = table(columns: ["x"], rows: [["1", "2"]])
note = callout(body: "hi")
```
"""


def types(markdown: str) -> dict[str, str]:
    page = render_page(markdown, "p.md")
    return {b.anchor: b.block_type for b in page.blocks}


def test_each_markdown_kind_has_its_type() -> None:
    got = types(DOC)
    assert got["title"] == "heading"
    assert [got[f"title/{n}"] for n in (1, 2, 3, 4)] == [
        "prose",
        "list",
        "table",
        "code",
    ]


def test_ui_statements_use_the_component_type() -> None:
    got = types(DOC)
    for name, component in (
        ("pick", "choice"),
        ("ship", "decision"),
        ("c", "chart"),
        ("note", "callout"),
    ):
        assert got[name] == component_block_type(component)
    assert got["bad"] == "visual"  # a bad prop still renders as its component


def test_wrapper_carries_type_and_id_next_to_anchor_and_hash() -> None:
    body = render_page(DOC, "p.md").body
    assert re.search(
        r'<div class="block" id="blk-title/1" data-anchor="title/1" '
        r'data-hash="[0-9a-f]{12}" data-block-type="prose">',
        body,
    )
    assert 'id="h-title"' in body and 'data-block-type="heading"' in body


def test_error_blocks() -> None:
    syntax = types("# T\n\n```ui\nx = table(columns:\n```\n")
    assert syntax["t/1"] == "error"
    removed = types("# T\n\n```custom\nx\n```\n")
    assert removed["t/1"] == "error"
    include = types('# T\n\n```ui\ni = include(source: "a.md")\n```\n')
    assert include["i"] == "error"


def test_unresolved_include_is_a_part() -> None:
    from varde_learn.docs.pages.render import PageCtx

    text = '```ui\ni = include(source: "a.md", select: "frontmatter")\n```\n'
    ctx = PageCtx("p.md")
    assert render_page(text, "p.md", ctx).blocks[0].block_type == "part"


def test_resolved_include_part_is_raw_and_keeps_its_data_part() -> None:
    from varde_learn.docs.pages.render import PageCtx

    part = '<section class="part" data-part="i"></section>'
    ctx = PageCtx("p.md", parts={"i": part})
    text = '```ui\ni = include(source: "a.md", select: "frontmatter")\n```\n'
    assert part in render_page(text, "p.md", ctx).body


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("rich-*.md")))
def test_ids_are_unique_on_rich_fixtures(path: Path) -> None:
    body = render_page(path.read_text(encoding="utf-8"), path.name).body
    # widget-internal ids (diagram nodes) are not wrapper ids and may repeat
    ids = re.findall(r'\bid="((?:blk|h)-[^"]+)"', body)
    assert len(ids) == len(set(ids))
    assert 'data-block-type="' in body


def test_wrapper_attributes_are_escaped() -> None:
    from varde_learn.docs.pages.render import _wrap

    out = _wrap('a"><b', "0" * 12, "x", 'v"><i')
    assert "<b" not in out and "<i" not in out
    assert out.count("&quot;") == 3


def test_hash_and_anchor_unchanged_by_types() -> None:
    page = render_page("# T\n\nhello\n", "p.md")
    assert [(b.anchor, b.start, b.end) for b in page.blocks] == [
        ("t", 0, 1),
        ("t/1", 2, 3),
    ]
