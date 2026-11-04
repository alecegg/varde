from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "retire_dead_mail.py"
SPEC = importlib.util.spec_from_file_location("retire_dead_mail", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_retirement_requires_allowlist_or_terminal_plan_and_protects_live_roles() -> (
    None
):
    plans = {"finished-plan"}
    assert MODULE.eligible_address("python-port-old", set(), plans)
    assert MODULE.eligible_address("finished-plan-builder", set(), plans)
    assert not MODULE.eligible_address("active-plan-builder", set(), plans)
    assert not MODULE.eligible_address(
        "python-port-workflow-builder",
        set(),
        plans,
        {"python-port-workflow"},
    )
    assert not MODULE.eligible_address("main", set(), plans)
    assert not MODULE.eligible_address("python-port-live", {"python-port-live"}, plans)
    assert not MODULE.eligible_address("builder:finished-plan", set(), plans)


def test_longest_plan_prefix_prevents_active_nested_plan_retirement() -> None:
    plans = {"shared-plan", "shared-plan-followup"}

    assert MODULE.address_plan_id("shared-plan-followup-builder", plans) == (
        "shared-plan-followup"
    )
    assert not MODULE.eligible_address(
        "shared-plan-followup-builder",
        set(),
        {"shared-plan"},
        plans,
    )


def test_dry_run_apply_restore_round_trip_is_idempotent(tmp_path: Path) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_workflow.inbox import append_message, read_all

    working = tmp_path / "working"
    working.mkdir()
    data = open_data(working, load_data_config())
    data.addresses.retire({"finished-plan-builder"}, set(), datetime.now(UTC))
    stale = datetime.now(UTC) - timedelta(days=45)
    message = append_message(
        "main", "python-port-old", "info", "stale", working=working, now=stale
    )
    audit_dir = tmp_path / "audit"
    dry_run = MODULE.write_dry_run(working, audit_dir)
    payload = json.loads(dry_run.read_text())
    assert payload["addresses"] == ["python-port-old"]

    first = MODULE.apply_dry_run(working, dry_run)
    second = MODULE.apply_dry_run(working, dry_run)
    audit = Path(first["audit"])
    assert first == second
    assert "python-port-old" in data.addresses.retired_records()
    assert any(row.id == message.id for row in read_all(working))

    restored = MODULE.restore(working, audit)
    assert restored["restored_addresses"] == ["python-port-old"]
    assert "python-port-old" not in data.addresses.retired_records()


def test_apply_retry_finishes_after_retirement_write_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_workflow.inbox import append_message

    working = tmp_path / "working"
    working.mkdir()
    append_message(
        "main",
        "python-port-old",
        "info",
        "stale",
        working=working,
        now=datetime.now(UTC) - timedelta(days=45),
    )
    dry_run = tmp_path / "audit"
    path = MODULE.write_dry_run(working, dry_run)
    original = MODULE.retirement.retire
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated interrupted retirement")
        return original(*args, **kwargs)

    monkeypatch.setattr(MODULE.retirement, "retire", fail_once)
    try:
        MODULE.apply_dry_run(working, path)
    except OSError as exc:
        assert "simulated" in str(exc)
    else:
        raise AssertionError("first retirement attempt should fail")

    assert MODULE.apply_dry_run(working, path)["addresses"] == ["python-port-old"]
    assert calls == 2


def test_recent_unread_blocks_all_mail_for_address_from_retirement(
    tmp_path: Path,
) -> None:
    from varde_workflow.inbox import append_message

    stale = datetime.now(UTC) - timedelta(days=45)
    append_message(
        "main", "zero-test-failures-worker", "info", "old", working=tmp_path, now=stale
    )
    append_message(
        "main",
        "zero-test-failures-worker",
        "info",
        "recent",
        working=tmp_path,
        now=datetime.now(UTC),
    )

    assert MODULE.build_dry_run(tmp_path)["addresses"] == []


def test_apply_rejects_a_dry_run_when_mail_changes(tmp_path: Path) -> None:
    from varde_workflow.inbox import append_message

    old = datetime.now(UTC) - timedelta(days=45)
    append_message(
        "main", "python-port-changing", "info", "old", working=tmp_path, now=old
    )
    dry_run = tmp_path / "audit"
    path = MODULE.write_dry_run(tmp_path, dry_run)
    append_message(
        "main",
        "python-port-changing",
        "info",
        "new unread",
        working=tmp_path,
        now=datetime.now(UTC),
    )

    try:
        MODULE.apply_dry_run(tmp_path, path)
    except ValueError as exc:
        assert "mail changed" in str(exc)
    else:
        raise AssertionError("stale dry-run must require operator review again")


def test_apply_uses_stored_message_content_not_edited_listing(tmp_path: Path) -> None:
    from varde_workflow.inbox import append_message

    append_message(
        "main",
        "python-port-audit-proof",
        "info",
        "source content",
        working=tmp_path,
        now=datetime.now(UTC) - timedelta(days=45),
    )
    audit_dir = tmp_path / "audit"
    dry_run = MODULE.write_dry_run(tmp_path, audit_dir)
    payload = json.loads(dry_run.read_text())
    payload["messages"][0]["text"] = "edited listing"
    dry_run.write_text(json.dumps(payload))

    result = MODULE.apply_dry_run(tmp_path, dry_run)
    archive = json.loads(Path(result["audit"]).read_text())

    assert archive["messages"][0]["text"] == "source content"
