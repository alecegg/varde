from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from varde_learn.loop.calls import SUCCESS, CallRow
from varde_learn.loop.guardrails import (
    Guardrail,
    check_owners,
    dead,
    firings,
    load_registry,
    validate_registry,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def _row(command: str, *, guardrail: str | None = None, age_days: int = 0) -> CallRow:
    row: CallRow = {
        "ts": (NOW - timedelta(days=age_days)).isoformat(),
        "command": command,
        "status": SUCCESS,
        "duration_s": 0.1,
        "session": None,
    }
    if guardrail is not None:
        row["guardrail"] = guardrail
    return row


def _entry(identifier: str, owner: str, **kwargs: str) -> Guardrail:
    entry: Guardrail = {
        "id": identifier,
        "kind": kwargs.get("kind", "cli-step"),
        "owner": owner,
        "purpose": "Test guardrail.",
    }
    if "command" in kwargs:
        entry["command"] = kwargs["command"]
    return entry


def test_load_registry_does_not_depend_on_current_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_registry()


def test_validate_rejects_duplicate_ids_and_missing_owners(tmp_path: Path) -> None:
    entry = _entry("same", "owner.py")
    (tmp_path / "owner.py").touch()
    with pytest.raises(ValueError, match="duplicate"):
        validate_registry([entry, entry])
    with pytest.raises(ValueError, match="owner file does not exist"):
        check_owners([_entry("missing", "missing.py")], tmp_path)


def test_check_owners_rejects_paths_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-owner.py"
    outside.touch()
    with pytest.raises(ValueError, match="owner file does not exist"):
        check_owners([_entry("escape", "../outside-owner.py")], tmp_path)


@pytest.mark.parametrize(
    "content",
    ["[[guardrails]\nid =", "id = 'missing array'", "guardrails = [1]"],
)
def test_load_registry_rejects_invalid_data(tmp_path: Path, content: str) -> None:
    path = tmp_path / "guardrails.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid guardrail registry"):
        load_registry(path)


def test_firings_match_command_prefix_and_explicit_fire() -> None:
    entries = [
        _entry("step", "unused", command="future step"),
        _entry("manual", "unused"),
    ]
    assert firings(
        entries,
        [
            _row("future step\t--option"),
            _row("future stepping"),
            _row("unrelated", guardrail="manual"),
            _row("future step", guardrail="step"),
        ],
    ) == {"step": {"fired": 2, "blocked": 0}, "manual": {"fired": 1, "blocked": 0}}


def test_dead_reports_zero_firings_in_window() -> None:
    entries = [
        _entry("recent", "unused", command="plan validate"),
        _entry("old", "unused", command="old command"),
    ]
    assert dead(
        entries,
        [
            _row("plan validate --all"),
            _row("old command", age_days=31),
            {**_row("old command"), "ts": "not-a-time"},
        ],
        timedelta(days=30),
        NOW,
    ) == ["old"]


def test_dead_includes_rows_exactly_at_cutoff_and_normalizes_times() -> None:
    entries = [_entry("edge", "unused", command="edge command")]
    exact_cutoff = (NOW - timedelta(days=30)).replace(tzinfo=None).isoformat()
    row = _row("edge command")
    row["ts"] = exact_cutoff
    assert dead(entries, [row], timedelta(days=30), NOW) == []


def test_firings_separates_blocked_from_fired():
    entries = [_entry("g", "unused")]
    fired = _row("guardrails fire g", guardrail="g")
    blocked = _row("guardrails fire g", guardrail="g")
    blocked["status"] = "blocked"
    assert firings(entries, [fired, blocked]) == {"g": {"fired": 1, "blocked": 1}}


@pytest.mark.parametrize("kind", ["gate", "cli-check"])
def test_failed_command_guardrail_counts_as_blocked(kind: str) -> None:
    entry = _entry("check", "unused", command="plan validate", kind=kind)
    failed = _row("plan validate artifact.md")
    failed["status"] = "failure"

    assert firings([entry], [failed]) == {"check": {"fired": 0, "blocked": 1}}
