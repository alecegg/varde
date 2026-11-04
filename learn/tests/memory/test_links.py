from typing import Any

from varde_learn.memory import links
from varde_learn.memory.entry import Entry

KEY = "repo-0123456789abcdef"


def make(entry_id: str, text: str = "body", **overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": "global",
        "scope_key": "",
        "text": text,
        "source": "t",
        "created": "c",
    }
    base.update(overrides)
    return Entry(**base)


def test_links_resolve_sibling_and_root_relative() -> None:
    entries = [
        make("a", "[b](b.md) and [p](project/" + KEY + "/p.md) and [x](x.md)"),
        make("b", "[a](a.md)"),
        make("p", scope="project", scope_key=KEY),
    ]
    graph = links.build_graph(entries)
    assert graph.broken == {"global/a.md": ["x.md"]}
    assert graph.inbound["global/b.md"] == ["global/a.md"]
    assert graph.inbound[f"project/{KEY}/p.md"] == ["global/a.md"]


def test_links_from_nested_entry_reach_root_relative_global() -> None:
    entries = [
        make("p", "[g](global/g.md)", scope="project", scope_key=KEY),
        make("g"),
    ]
    assert links.build_graph(entries).inbound["global/g.md"] == [f"project/{KEY}/p.md"]


def test_links_lint_warns_broken_and_orphan_only() -> None:
    entries = [make("a", "[b](b.md) [gone](gone.md)"), make("b", "[web](https://x.y)")]
    issues = links.lint_links(entries)
    assert [(i.code, i.path) for i in issues] == [
        ("link-broken", "global/a.md"),
        ("orphan", "global/a.md"),
    ]
    assert {i.severity for i in issues} == {"warning"}


def test_links_ignore_self_code_and_non_markdown() -> None:
    text = "[me](a.md) `[c](c.md)` [img](pic.png) [anchor](#top)"
    graph = links.build_graph([make("a", text)])
    assert graph.broken == {}
    assert graph.inbound["global/a.md"] == []


def test_links_linked_by_sorted() -> None:
    entries = [make("t"), make("z", "[t](t.md)"), make("a", "[t](t.md)")]
    assert links.linked_by(entries, entries[0]) == ["global/a.md", "global/z.md"]
