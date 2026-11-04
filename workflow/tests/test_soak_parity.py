from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from varde_data.messages import open_messages
from varde_data.records.messages import NewMessage
from varde_data.store_mode import mark_import_verified, set_store_mode
from varde_workflow.commands import msg_soak
from varde_workflow.inbox import append_message, record_delivery
from varde_workflow.soak import evaluate

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def _records(**overrides):
    data = {
        "messages": [],
        "deliveries": [],
        "relay_events": [],
        "live_addresses": set(),
        "nudges": [],
        "status": {"exit_code": 0},
        "approved_merges": [],
        "open_requests": [],
        "active_orchestrators_today": 1,
        "prior_days": [],
    }
    data.update(overrides)
    return data


def _open_mirror(working: Path) -> Any:
    mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    return open_messages(working, "files")


def _criterion(report, identifier):
    return next(item for item in report["criteria"] if item["id"] == identifier)


def test_existing_soak_criteria_are_unchanged_when_mirror_parity_is_added():
    baseline = evaluate(_records(), 1, NOW, {})
    mirrored = evaluate(_records(parity={"compared": 1}), 1, NOW, {})

    assert list(baseline["criteria"]) == [
        item for item in mirrored["criteria"] if item["id"] != "parity"
    ]
    assert _criterion(mirrored, "parity") == {
        "id": "parity",
        "value": 0,
        "threshold": 0,
        "ok": True,
        "n": 1,
        "insufficient": False,
    }


def test_parity_is_reported_as_no_data_below_compare_minimum():
    report = evaluate(_records(parity={"compared": 0}), 1, NOW, {})

    assert _criterion(report, "parity") == {
        "id": "parity",
        "value": "no-data",
        "threshold": 0,
        "ok": False,
        "n": 0,
        "insufficient": True,
    }


def test_mirror_failures_and_lag_fail_parity_even_without_divergence():
    for parity in (
        {"compared": 1, "mirror-failure": 1},
        {"compared": 1, "lag": 1},
    ):
        result = _criterion(evaluate(_records(parity=parity), 1, NOW, {}), "parity")
        assert result["value"] == 1
        assert result["ok"] is False


def test_failed_parity_write_is_counted_as_parity_failure():
    result = _criterion(
        evaluate(_records(parity={"compared": 1, "mirror-failure": 1}), 1, NOW, {}),
        "parity",
    )

    assert result["value"] == 1
    assert result["ok"] is False


def test_unreadable_parity_is_scored_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".cache" / "inbox").mkdir(parents=True)
    repository = _open_mirror(tmp_path)
    monkeypatch.setattr(
        repository,
        "_connect",
        lambda **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )

    parity = repository.parity_report()
    result = _criterion(evaluate(_records(parity=parity), 1, NOW, {}), "parity")

    assert parity == {"mirror-failure": 1}
    assert result["ok"] is False


def test_failed_mirror_write_is_counted_in_soak_parity(tmp_path: Path, monkeypatch):
    (tmp_path / ".cache" / "inbox").mkdir(parents=True)
    repository = _open_mirror(tmp_path)

    def fail_write(_rows):
        raise OSError("mirror unavailable")

    monkeypatch.setattr(repository.mirror, "import_messages", fail_write)
    repository.append(NewMessage("main", "reader", "info", "message", ts="t"))

    parity = repository.parity_report()
    result = _criterion(evaluate(_records(parity=parity), 1, NOW, {}), "parity")

    assert parity["mirror-failure"] == 1
    assert parity["lag"] == 1
    assert result["n"] == 2
    assert result["ok"] is False


@pytest.mark.parametrize("mode", ["files", "sqlite", "mirror-files", "mirror-sqlite"])
def test_gather_reads_same_message_and_event_from_all_message_backends(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    working = tmp_path / mode
    (working / ".cache" / "inbox").mkdir(parents=True)
    if mode != "files":
        mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
        for step in ("mirror-files", "mirror-sqlite", "sqlite"):
            set_store_mode(working, step)
            if step == mode:
                break

    message = append_message(
        "main",
        "orchestrator-1",
        "info",
        "golden message",
        working=working,
        now=NOW.replace(hour=10),
    )
    record_delivery(
        working,
        message.id or "",
        "orchestrator-1",
        now="2026-10-23T10:00:30Z",
    )
    monkeypatch.setattr(msg_soak, "load_relay", lambda _working: {})
    monkeypatch.setattr(
        msg_soak, "load_report", lambda _working, _now: {"exit_code": 0}
    )
    monkeypatch.setattr(msg_soak, "filter_retired", lambda status, _retired: status)
    monkeypatch.setattr(msg_soak, "load_retired", lambda _working: {})
    monkeypatch.setattr(msg_soak, "_approved_merges", lambda _working, _repo: [])
    monkeypatch.setattr(msg_soak, "load_nudges", lambda _working: [])
    monkeypatch.setattr(msg_soak, "_prior_days", lambda _working, _today: [])
    addresses = SimpleNamespace(
        resolve_alias=lambda address: address,
        live_addresses=lambda _now: {"orchestrator-1"},
    )
    monkeypatch.setattr(
        msg_soak, "open_data", lambda *_args: SimpleNamespace(addresses=addresses)
    )

    parity_windows: list[int] = []
    original_parity = msg_soak.mirror_parity

    def record_parity(path, backend_name, *, window=7):
        parity_windows.append(window)
        return original_parity(path, backend_name, window=window)

    monkeypatch.setattr(msg_soak, "mirror_parity", record_parity)
    data = msg_soak.gather(working, NOW, tmp_path, window_days=3)
    assert ("parity" in data) == mode.startswith("mirror-")
    assert parity_windows == [3]
    report = evaluate(data, 1, NOW, {})

    assert [item["id"] for item in data["messages"]] == [message.id]
    assert [item["message_id"] for item in data["deliveries"]] == [message.id]
    assert _criterion(report, "delivered-latency")["value"] == 30.0
    criteria = [
        (item["id"], item["value"], item["threshold"], item["n"], item["ok"])
        for item in report["criteria"]
    ]
    expected = [
        ("delivered-latency", 30.0, 120, 1, True),
        ("ack-latency", None, 1800, 0, True),
        ("main-nudges", 0, 0, 0, True),
        ("replays", 0, 0, 1, True),
        ("status-clean", 0, 0, 1, True),
        ("send-no-mailman", None, 0.02, 0, True),
        ("merge-guard", 0, 0, 0, True),
    ]
    if mode.startswith("mirror-"):
        expected.append(("parity", 0, 0, 1, True))
    assert criteria == expected
