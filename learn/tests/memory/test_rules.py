from dataclasses import replace
from typing import Any

import pytest
from varde_learn.memory.entry import Entry
from varde_learn.memory.rules import ERROR, WARNING, lint_entry

LONG = "x" * 81


def make(**overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": "e1",
        "scope": "global",
        "scope_key": "",
        "text": "note",
        "source": "test",
        "created": "2026-11-01T00:00:00Z",
    }
    base.update(overrides)
    return Entry(**base)


def codes(issues, severity: str) -> set[str]:
    return {i.code for i in issues if i.severity == severity}


def test_clean_entry_has_no_issues() -> None:
    assert lint_entry(make(), None) == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"id": "../x"}, "slug-bad"),
        ({"scope": "skill", "scope_key": "../x"}, "scope-key-bad"),
        ({"text": " \n"}, "body-empty"),
        ({"text": "token = abcdefghijkl"}, "secret"),
        ({"valid_until": "2026-13-40"}, "valid-until-bad"),
    ],
)
def test_lint_errors(overrides, code) -> None:
    assert code in codes(lint_entry(make(**overrides), None), ERROR)


def test_valid_until_date_ok() -> None:
    assert lint_entry(make(valid_until="2026-12-31"), None) == []


def test_unified_model_long_summary_is_error_when_new() -> None:
    assert "summary-surface" in codes(lint_entry(make(text=LONG), None), ERROR)


def test_grandfather_legacy_long_summary_is_warning() -> None:
    entry = make(text=LONG)
    issues = lint_entry(entry, entry)
    assert "summary-surface" in codes(issues, WARNING)
    assert not codes(issues, ERROR)


def test_grandfather_ends_when_summary_changes() -> None:
    old = make(text=LONG)
    new = replace(old, text=LONG + "y")
    assert "summary-surface" in codes(lint_entry(new, old), ERROR)


def test_unsurfaced_long_summary_is_not_an_error() -> None:
    issues = lint_entry(make(text=LONG, surface=False), None)
    assert not codes(issues, ERROR)


def test_description_is_the_summary() -> None:
    assert not codes(lint_entry(make(text="y" * 200, description="short"), None), ERROR)


def test_warnings() -> None:
    issues = lint_entry(make(text="a" * 9000, type="odd", surface=False), None)
    assert codes(issues, WARNING) >= {"body-long", "type-unknown", "summary-long"}
