from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import cast

import pytest
from varde_data.queue import open_queue
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_data.repos.queue import QueueRepository
from varde_workflow import cli
from varde_workflow.commands import plan_queue_roles
from varde_workflow.role_queue_budget import BudgetLimits, ResourceSnapshot
from varde_workflow.role_queue_independence import readiness


@pytest.mark.parametrize(
    ("argv", "action"),
    [
        (
            [
                "plan",
                "queue",
                "pull",
                "--role",
                "builder",
                "--slot",
                "s1",
                "--epoch",
                "3",
            ],
            "pull",
        ),
        (["plan", "queue", "renew", "--slot", "s1", "--epoch", "3"], "renew"),
        (
            ["plan", "queue", "finish", "--slot", "s1", "--epoch", "3", "--item", "i1"],
            "finish",
        ),
        (
            [
                "plan",
                "queue",
                "release",
                "--slot",
                "s1",
                "--epoch",
                "3",
                "--item",
                "i1",
            ],
            "release",
        ),
        (["plan", "queue", "status"], "status"),
        (["plan", "queue", "metrics"], "metrics"),
        (
            [
                "plan",
                "queue",
                "enqueue",
                "--plan-dir",
                "/plans/p",
                "--id",
                "i1",
                "--role",
                "builder",
            ],
            "enqueue",
        ),
    ],
)
def test_role_queue_commands_parse(argv: list[str], action: str) -> None:
    args = cli._parser().parse_args(argv)
    assert args.queue_action == action
    if action in {"pull", "renew", "finish", "release"}:
        assert args.slot == "s1"
        assert args.epoch == 3


def test_slot_commands_require_slot_and_epoch() -> None:
    with pytest.raises(ValueError, match="required"):
        cli._parser().parse_args(["plan", "queue", "renew"])


def test_status_reports_pending_migration_without_opening_merged_queue(
    tmp_path,
) -> None:
    initialize(tmp_path)
    marker = tmp_path / ".cache/data/queue.version"
    marker.write_text("3\n", encoding="ascii")

    result = plan_queue_roles._run(SimpleNamespace(queue_action="status"), tmp_path)

    assert result["message"] == (
        "queue migration pending: run varde plan queue merge-role-inbox"
    )
    assert result["migration_message"] == result["message"]


def test_parent_help_lists_role_commands() -> None:
    output = cli.help_text("plan queue")
    assert "pull" in output
    assert "--epoch" in output


def test_snapshot_file_is_decoded(tmp_path) -> None:
    snapshot_path = tmp_path / ".cache/data/resources.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "taken_at": "2026-10-27T10:00:00+00:00",
                "providers": {"test": 0.2},
                "rss_mb": 10,
                "cpu_pct": 4,
                "processes": 5,
                "live_workers": 2,
            }
        ),
        encoding="utf-8",
    )
    result = plan_queue_roles._snapshot(tmp_path)
    assert isinstance(result, ResourceSnapshot)
    assert result.providers == {"test": 0.2}


def test_status_blocks_queued_dependency_and_accepts_merged_dependency(
    monkeypatch, tmp_path
) -> None:
    initialize(tmp_path)
    repo = open_queue(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    repo.enqueue(
        QueueItemInput(
            "queued-dependency", "plan", role="builder", queue_name="roles/global"
        )
    )
    repo.enqueue(
        QueueItemInput(
            "queued-dependent",
            "plan",
            role="reviewer",
            queue_name="roles/global",
            depends_on=("queued-dependency",),
        )
    )
    repo.enqueue(
        QueueItemInput(
            "merged-dependency", "plan", role="builder", queue_name="roles/global"
        )
    )
    repo.transition("roles/global", "merged-dependency", "merged", actor="test")
    repo.enqueue(
        QueueItemInput(
            "merged-dependent",
            "plan",
            role="builder",
            queue_name="roles/global",
            depends_on=("merged-dependency",),
        )
    )
    snapshot = ResourceSnapshot(
        taken_at=plan_queue_roles.datetime.now(plan_queue_roles.UTC),
        providers={},
        rss_mb=0,
        cpu_pct=0,
        processes=0,
        live_workers=0,
    )
    monkeypatch.setattr(plan_queue_roles, "_snapshot", lambda _working: snapshot)
    monkeypatch.setattr(
        plan_queue_roles,
        "load_limits",
        lambda _path: (BudgetLimits({}, 1000, 100, 100, 24), ""),
    )

    status = plan_queue_roles._status(
        cast("QueueRepository", repo), tmp_path, "roles/global"
    )

    assert status["roles"]["builder"]["ready"] == 2
    assert status["roles"]["reviewer"]["ready"] == 0
    assert status["roles"]["reviewer"]["blocked_by"] == [
        {
            "item_id": "queued-dependent",
            "reason": "depends_on item queued-dependency is unmerged",
        }
    ]
    dependent = repo.get("roles/global", "merged-dependent")
    assert readiness(dependent, (), unmerged_dependencies=set()).ok


def test_json_command_output_uses_success_envelope(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setattr(
        plan_queue_roles.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    monkeypatch.setattr(plan_queue_roles, "_run", lambda _args, _working: {"ok": True})
    assert plan_queue_roles.run(SimpleNamespace(queue_action="status", json=True)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["data"] == {"ok": True}
