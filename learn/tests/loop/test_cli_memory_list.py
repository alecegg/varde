from datetime import date
from typing import Any

from varde_learn.loop import cli_memory_list as lister
from varde_learn.memory.entry import Entry

TODAY = date(2026, 11, 1)


def make(entry_id: str, scope: str = "global", **overrides) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": scope,
        "scope_key": "" if scope == "global" else "k",
        "text": "body",
        "source": "t",
        "created": "c",
    }
    base.update(overrides)
    return Entry(**base)


def test_memory_list_counts_per_scope_and_warning() -> None:
    entries = [
        make("a"),
        make("b"),
        make("c", scope="skill"),
        make("d", status="retired"),
    ]
    counts = lister.scope_counts(entries)
    assert counts == {"agent": 0, "skill": 1, "project": 0, "global": 2}
    assert lister.scope_warnings(counts, 2) == []
    assert lister.scope_warnings(counts, 1) == [
        "warning: scope global has 2 entries (limit 1)"
    ]
    lines = lister.counts_lines(counts, 1)
    assert lines[:4] == ["agent: 0", "skill: 1", "project: 0", "global: 2"]
    assert lines[4].startswith("warning: scope global")


def test_memory_list_counts_expired_report() -> None:
    entries = [make("old", valid_until="2026-01-01"), make("new")]
    assert lister.expired_lines(entries, TODAY) == ["old | global | expired 2026-01-01"]
