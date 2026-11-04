from varde_learn.memory.entry import Entry
from varde_learn.memory.index import build_index, render_index


def entry(id, scope="global", key="", text="t", created="2026-01-01", tags=()):
    return Entry(
        id=id,
        scope=scope,
        scope_key=key,
        text=text,
        source="s",
        created=created,
        tags=tags,
        model="m",
        harness_version="1",
    )


def test_order_is_scope_created_id() -> None:
    entries = [
        entry("b", "global", created="2026-01-02"),
        entry("a", "global", created="2026-01-02"),
        entry("z", "agent", "x"),
        entry("p", "project", "n-0123456789abcdef"),
        entry("s", "skill", "k"),
        entry("o", "global", created="2026-01-01"),
    ]
    assert [line.id for line in build_index(entries)] == [
        "z",
        "s",
        "p",
        "o",
        "a",
        "b",
    ]


def test_summary_first_line_capped_at_80() -> None:
    line = build_index([entry("a", text="x" * 100 + "\nsecond")])[0]
    assert line.summary == "x" * 80


def test_render_line_format() -> None:
    lines = build_index([entry("a", text="hello\nmore", tags=("t1", "t2"))])
    assert render_index(lines) == "a | global | hello | t1,t2"
