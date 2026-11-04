from datetime import date
from typing import Any

from varde_learn.knowledge.memory_config import Config
from varde_learn.memory.entry import Entry
from varde_learn.memory.expiry import expired_report, is_expired

TODAY = date(2026, 11, 1)


def make(entry_id: str, **overrides) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": "global",
        "scope_key": "",
        "text": "body",
        "source": "t",
        "created": "c",
    }
    base.update(overrides)
    return Entry(**base)


def test_expiry_is_expired_boundaries() -> None:
    assert not is_expired(make("a"), TODAY)
    assert not is_expired(make("a", valid_until="2026-11-01"), TODAY)
    assert is_expired(make("a", valid_until="2026-10-31"), TODAY)
    assert not is_expired(make("a", valid_until="not-a-date"), TODAY)


def test_expiry_report_lists_only_active_expired_sorted() -> None:
    entries = [
        make("late", valid_until="2026-10-30"),
        make("early", valid_until="2026-01-01"),
        make("fresh", valid_until="2027-01-01"),
        make("none"),
        make("done", valid_until="2026-01-01", status="retired"),
    ]
    assert [e.id for e in expired_report(entries, TODAY)] == ["early", "late"]


def test_expiry_scope_warn_config() -> None:
    assert Config.from_toml("").memory.scope_warn() == (50, None)
    assert Config.from_toml("[memory]\nscope_warn = 3\n").memory.scope_warn() == (
        3,
        None,
    )
    value, error = Config.from_toml("[memory]\nscope_warn = 0\n").memory.scope_warn()
    assert value == 50
    assert error is not None
