from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import cast

import pytest
from varde_data.errors import Invalid
from varde_data.queue import open_queue
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItem, QueueItemInput
from varde_data.repos.queue import QueueRepository
from varde_data.role_inbox import RoleInbox
from varde_workflow import cli
from varde_workflow.commands import plan_queue_roles
from varde_workflow.role_queue_budget import BudgetLimits, ResourceSnapshot
from varde_workflow.role_queue_flow import (
    FOLLOWUP_CAP,
    follow_up,
    follow_up_cap_reached,
)


def _sqlite_queue(path):
    initialize(path)
    repo = open_queue(path)
    with sqlite3.connect(path / QUEUE_DATABASE) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    return repo


def test_unknown_dependency_status_is_waiting_on_unwritten(monkeypatch, tmp_path):
    repo = _sqlite_queue(tmp_path)
    repo.enqueue(
        QueueItemInput(
            "dependent",
            "plan",
            depends_on=("future-item",),
            role="builder",
            queue_name="roles/global",
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

    assert status["roles"]["builder"]["ready"] == 0
    assert status["roles"]["builder"]["blocked_by"] == [
        {"item_id": "dependent", "reason": "waiting-on-unwritten"}
    ]


def test_automatic_followups_increment_depth_and_stop_at_cap():
    item = QueueItem("review", "plan", role="reviewer", followup_depth=2)

    next_item = follow_up(item, "findings")

    assert len(next_item) == 1
    assert next_item[0].role == "builder"
    assert next_item[0].followup_depth == FOLLOWUP_CAP
    at_cap = QueueItem("at-cap", "plan", role="reviewer", followup_depth=FOLLOWUP_CAP)
    assert follow_up(at_cap, "findings") == ()
    assert follow_up_cap_reached(at_cap, "findings")


def test_builder_finish_never_reaches_cap():
    builder = QueueItem("build", "plan", role="builder", followup_depth=FOLLOWUP_CAP)

    assert not follow_up_cap_reached(builder, "done")


def test_specialist_review_findings_respect_followup_cap():
    assert (
        follow_up(
            QueueItem(
                "review", "plan", role="accessibility", followup_depth=FOLLOWUP_CAP
            ),
            "findings",
        )
        == ()
    )
    assert follow_up_cap_reached(
        QueueItem("review", "plan", role="accessibility", followup_depth=FOLLOWUP_CAP),
        "findings",
    )


def test_enqueue_parent_sets_depth_and_refuses_past_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(RoleInbox, "slots", lambda _self: object())
    repo = _sqlite_queue(tmp_path)
    repo.enqueue(
        QueueItemInput(
            "parent",
            "plan",
            queue_name="roles/global",
            followup_depth=FOLLOWUP_CAP - 1,
        )
    )
    args = SimpleNamespace(
        queue_action="enqueue",
        queue="roles/global",
        plan_dir=str(tmp_path),
        id="child",
        role="builder",
        owned_file=[],
        depends_on=[],
        serialize_with=[],
        kind="build",
        parent="parent",
    )

    result = plan_queue_roles._run(args, tmp_path)

    assert result["item"]["followup_depth"] == FOLLOWUP_CAP
    args.id = "over-cap"
    repo.enqueue(
        QueueItemInput(
            "over-cap-parent",
            "plan",
            queue_name="roles/global",
            followup_depth=FOLLOWUP_CAP,
        )
    )
    args.parent = "over-cap-parent"
    with pytest.raises(Invalid, match="cap-reached"):
        plan_queue_roles._run(args, tmp_path)


def test_enqueue_cli_parent_at_cap_returns_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(RoleInbox, "slots", lambda _self: object())
    monkeypatch.setattr(
        plan_queue_roles.MemoryPaths,
        "resolve",
        lambda _cwd: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    repo = _sqlite_queue(tmp_path)
    repo.enqueue(
        QueueItemInput(
            "at-cap",
            "plan",
            queue_name="roles/global",
            followup_depth=FOLLOWUP_CAP,
        )
    )
    args = cli._parser().parse_args(
        [
            "plan",
            "queue",
            "enqueue",
            "--plan-dir",
            str(tmp_path),
            "--id",
            "over-cap",
            "--role",
            "builder",
            "--parent",
            "at-cap",
        ]
    )

    result = plan_queue_roles.run(args)

    assert result != 0
    assert "cap-reached" in capsys.readouterr().err
