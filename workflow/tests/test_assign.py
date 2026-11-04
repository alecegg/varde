from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from varde_workflow.commands.assign import run


def test_assign_sets_and_clears_assigned_to(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    plan = tmp_path / "working" / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: demo\nstatus: active\n---\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert run(Namespace(plan="demo", slot="orchestrator-2", clear=False)) == 0
    assert "assigned_to: orchestrator-2" in plan.read_text()
    slot_record = (
        tmp_path / "working" / ".cache" / "inbox" / "slots" / "orchestrator-2.json"
    )
    assert '"aliases": ["demo"]' in slot_record.read_text()
    assert run(Namespace(plan="demo", slot="orchestrator-3", clear=False)) == 0
    assert "assigned_to: orchestrator-3" in plan.read_text()
    assert '"aliases": []' in slot_record.read_text()
    new_slot_record = slot_record.with_name("orchestrator-3.json")
    assert '"aliases": ["demo"]' in new_slot_record.read_text()

    assert run(Namespace(plan="demo", slot=None, clear=True)) == 0
    assert "assigned_to:" not in plan.read_text()
    assert '"aliases": []' in new_slot_record.read_text()


def test_assign_rejects_non_orchestrator_slot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    plan = tmp_path / "working" / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: demo\nstatus: active\n---\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert run(Namespace(plan="demo", slot="orchestrator-2", clear=False)) == 0
    slots = tmp_path / "working" / ".cache" / "inbox" / "slots"
    before = {path.name: path.read_bytes() for path in slots.glob("*.json")}
    plan_before = plan.read_bytes()
    assert run(Namespace(plan="demo", slot="main", clear=False)) == 1
    assert plan.read_bytes() == plan_before
    assert {path.name: path.read_bytes() for path in slots.glob("*.json")} == before
