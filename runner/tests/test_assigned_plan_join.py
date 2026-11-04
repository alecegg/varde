from __future__ import annotations

from varde_runner.varde_cli import VardeCLI
from varde_runner.web.app import _plan_rows


def test_backlog_assigned_plan_joins_expected_orchestrator_row() -> None:
    """Pin the assigned-plan join behaviour fixed in aa19dc3a."""
    plans, _, _ = _plan_rows(
        {"plans": []},
        {"events": []},
        [],
        object(),
        [{"address": "orchestrator-2", "wake_context": {"paseo_id": "orch-2"}}],
        [{"id": "orch-2", "status": "idle"}],
        assigned_plans=[
            {
                "id": "2026-10-22-dashboard-assigned-plan-join",
                "status": "backlog",
                "title": "Dashboard assigned plan join",
                "assigned_to": "orchestrator-2",
            }
        ],
    )
    assert len(plans) == 1
    assert plans[0]["plan_id"] == "2026-10-22-dashboard-assigned-plan-join"
    assert plans[0]["plan_joined"] is True


def test_assigned_plan_reader_excludes_archived_plans(tmp_path) -> None:
    active = tmp_path / "plans" / "active"
    archived = tmp_path / "plans" / "archive" / "old"
    active.mkdir(parents=True)
    archived.mkdir(parents=True)
    (active / "plan.md").write_text(
        (
            "---\ntype: plan\nassigned_to: orchestrator-2\ndepends_on: [alpha]\n"
            "shared: [uv.lock]\n---\n"
        ),
        encoding="utf-8",
    )
    (archived / "plan.md").write_text(
        "---\ntype: plan\nassigned_to: orchestrator-2\n---\n", encoding="utf-8"
    )

    plans = VardeCLI(
        cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)}
    ).read_assigned_plans()

    assert [plan["id"] for plan in plans] == ["active"]
    assert plans[0]["depends_on"] == ["alpha"]
    assert plans[0]["shared"] == ["uv.lock"]


def test_orchestrator_row_owner_falls_back_to_assigned_to_then_address() -> None:
    plans, _, _ = _plan_rows(
        {"plans": []},
        {"events": []},
        [],
        object(),
        [
            {"address": "orchestrator-2", "wake_context": {"paseo_id": "orch-2"}},
            {"address": "orchestrator-3", "wake_context": {"paseo_id": "orch-3"}},
        ],
        [{"id": "orch-2", "status": "idle"}, {"id": "orch-3", "status": "idle"}],
        assigned_plans=[
            {
                "id": "assigned-plan",
                "status": "backlog",
                "title": "Assigned",
                "assigned_to": "orchestrator-2",
            }
        ],
    )
    owners = {plan["address"]: plan["owner"] for plan in plans}
    assert owners["orchestrator-2"] == "orchestrator-2"
    assert owners["orchestrator-3"] == "orchestrator-3"
