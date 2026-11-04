from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime

import pytest
from varde_workflow.binding import BindingStore
from varde_workflow.commands.address import run as run_address
from varde_workflow.inbox import append_message, claim_unread, unread
from varde_workflow.slots import (
    add_alias,
    is_orchestrator_slot,
    is_pipeline_worker_slot,
    resolve_alias,
    resolve_reader,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def test_takeover_reads_slot_and_alias_history(tmp_path):
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    old_slot = append_message(
        "main", "orchestrator-1", "info", "slot mail", working=tmp_path
    )
    old_plan = append_message("main", "plan-a", "info", "plan mail", working=tmp_path)

    messages = claim_unread(tmp_path, "orchestrator-1", "new-session", "cli")

    assert [item.id for item in messages] == [old_slot.id, old_plan.id]


def test_claiming_slot_and_aliases_does_not_replay_delivered_messages(tmp_path):
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    message = append_message(
        "sender", "orchestrator-1", "info", "hello", working=tmp_path
    )

    assert [
        item.id for item in claim_unread(tmp_path, "orchestrator-1", "cli", "cli")
    ] == [message.id]
    for reader in ("plan-a", "orchestrator-1", "plan-a"):
        assert claim_unread(tmp_path, reader, "hook", "hook") == []


def test_unread_resolves_alias_to_claimed_slot(tmp_path):
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    append_message("sender", "orchestrator-1", "info", "hello", working=tmp_path)

    assert len(claim_unread(tmp_path, "orchestrator-1", "cli", "cli")) == 1
    assert unread(tmp_path, "plan-a") == []


def test_literal_plan_id_is_not_resolved_without_alias(tmp_path):
    assert resolve_reader("plan-a", tmp_path) == "plan-a"


def test_status_groups_alias_messages_under_slot(tmp_path):
    from varde_workflow.msg_status import load_report

    add_alias(tmp_path, "orchestrator-1", "plan-a")
    append_message("main", "plan-a", "info", "plan mail", working=tmp_path)

    report = load_report(str(tmp_path), datetime.now(UTC))

    assert [row["address"] for row in report["addresses"]] == ["orchestrator-1"]
    assert report["addresses"][0]["unread"] == 1


def test_slot_file_keeps_aliases_and_current_address(tmp_path):
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    path = tmp_path / ".cache" / "inbox" / "slots" / "orchestrator-1.json"
    assert json.loads(path.read_text()) == {
        "slot": "orchestrator-1",
        "aliases": ["plan-a"],
        "current_address": "orchestrator-1",
    }


def test_resolution_logic_is_pure():
    assert (
        resolve_alias("plan-a", {"orchestrator-1": {"aliases": ["plan-a"]}})
        == "orchestrator-1"
    )


def test_ordinary_address_does_not_create_slot_or_supersede_live_binding(
    tmp_path, capsys
):
    store = BindingStore(tmp_path)
    now = datetime.now(UTC)
    marker = store.issue("plan-alpha", now=now)
    assert store.redeem(marker, "old", "claude", "/repo", now=now)

    args = Namespace(
        address_action="new",
        name="plan-alpha",
        plan=None,
        ttl=86400,
        uses=1,
        supersede=False,
    )
    with pytest.raises(ValueError, match="supersede"):
        run_address(args, tmp_path)

    assert not (tmp_path / ".cache/inbox/slots/plan-alpha.json").exists()
    assert capsys.readouterr().out == ""


def test_orchestrator_slot_creates_record_and_auto_supersedes(tmp_path, capsys):
    args = Namespace(
        address_action="new",
        name="orchestrator-1",
        plan=None,
        ttl=86400,
        uses=1,
        supersede=False,
    )
    assert is_orchestrator_slot(args.name)
    assert run_address(args, tmp_path) == 0
    marker = capsys.readouterr().out.strip()
    store = BindingStore(tmp_path)
    assert store.redeem(marker, "old", "claude", "/repo", now=NOW)

    assert run_address(args, tmp_path) == 0
    assert capsys.readouterr().out.strip()
    assert (tmp_path / ".cache/inbox/slots/orchestrator-1.json").exists()


def test_address_plan_alias_requires_stable_slot(tmp_path):
    args = Namespace(
        address_action="new",
        name="main",
        plan="demo",
        ttl=86400,
        uses=1,
        supersede=False,
    )
    with pytest.raises(ValueError, match="orchestrator-<n>"):
        run_address(args, tmp_path)
    assert not (tmp_path / ".cache/inbox/slots/main.json").exists()


def test_pipeline_worker_slot_takeover_preserves_plan_alias(tmp_path, capsys):
    args = Namespace(
        address_action="new",
        name="demo-builder",
        plan="demo",
        ttl=86400,
        uses=1,
        supersede=False,
    )
    assert is_pipeline_worker_slot(args.name)
    assert is_pipeline_worker_slot(args.name, args.plan)
    assert not is_pipeline_worker_slot(args.name, "other")
    assert run_address(args, tmp_path) == 0
    old_marker = capsys.readouterr().out.strip()
    store = BindingStore(tmp_path)
    assert store.redeem(old_marker, "old", "codex", "/repo", now=NOW)

    assert run_address(args, tmp_path) == 0
    new_marker = capsys.readouterr().out.strip()
    assert store.redeem(new_marker, "new", "codex", "/repo", now=NOW)
    assert (tmp_path / ".cache/inbox/slots/demo-builder.json").exists()
    assert resolve_reader("demo", tmp_path) == "demo-builder"


def test_alias_resolution_is_deterministic_when_records_conflict():
    records: dict[str, dict[str, object]] = {
        "orchestrator-2": {"aliases": ["plan-a"]},
        "orchestrator-1": {"aliases": ["plan-a"]},
    }
    assert resolve_alias("plan-a", records) == "orchestrator-1"
