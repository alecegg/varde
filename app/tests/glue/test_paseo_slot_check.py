from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from varde import fastpath
from varde.glue import handoff_checkpoint
from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.queue_store import initialize


def _status(
    agent_id: str = "paseo-agent-1", cursor: str = "turn-1", tokens: int = 250_000
) -> dict:
    return {
        "agentId": agent_id,
        "activityCursor": cursor,
        "contextWindowUsedTokens": tokens,
        "usage": {"total_tokens": 7_500},
    }


def _checkpoint(agent_id: str, turn: int, item: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": agent_id,
        "harness": "paseo",
        "role": "builder",
        "turn": turn,
        "current_item": item,
        "worktree": "/worktrees/p6",
        "branch": "p6",
        "last_commit": "abc123",
        "queue_position": 1,
        "decisions_made": [],
        "pending_findings": [],
        "next_actions": ["handoff"],
        "files_touched": [],
        "token_usage": {"status": "reported", "cumulative_tokens": 7_500},
    }


def _store_plan(tmp_path: Path) -> Path:
    working = tmp_path / "memory"
    working.mkdir()
    initialize(working)
    database = working / ".cache" / "inbox" / "messages.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    marker = working / ".cache" / "data" / "queue.version"
    assert marker.read_text(encoding="ascii").strip() == "4"
    plan_dir = working / "plans" / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    return plan_dir


def _slots(plan_dir: Path):
    working = plan_dir.parent.parent
    return open_data(working, load_data_config()).slots


def _slot(plan_dir: Path):
    return _slots(plan_dir).show("builder-1")


def _run_check(
    plan_dir: Path,
    status_file: Path,
    capsys,
    slot: str = "builder-1",
    status: dict | None = None,
) -> dict:
    status_file.write_text(json.dumps(status or _status()), encoding="utf-8")
    result = fastpath.run(
        [
            "hook",
            "pipeline-slot-check",
            "--plan-dir",
            str(plan_dir),
            "--slot",
            slot,
            "--role",
            "builder",
            "--item",
            "p6-enforce-handoff",
            "--status-file",
            str(status_file),
        ]
    )
    assert result == 0
    return json.loads(capsys.readouterr().out)


def test_paseo_slot_check_requires_checkpoint_then_emits_handoff(
    tmp_path: Path, capsys
) -> None:
    plan_dir = _store_plan(tmp_path)
    status_file = tmp_path / "status.json"

    requested = _run_check(plan_dir, status_file, capsys)

    assert requested["action"] == "checkpoint_required"
    assert requested["turn_count"] == 1
    assert "Write the full structured checkpoint" in requested["prompt"]

    recorded = _slot(plan_dir)
    assert recorded.agent_ref == "paseo-agent-1"
    assert recorded.turn_count == 1
    assert recorded.context_tokens == 250_000
    projection = json.loads(
        (plan_dir / "notes" / "slot-turns" / "builder-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert projection["turn_count"] == 1
    assert projection["slot_epoch"] == 1

    checkpoint_root = plan_dir / "notes" / "checkpoints" / "plan-builder"
    handoff_checkpoint.write_checkpoint(
        checkpoint_root,
        _checkpoint("paseo-agent-1", 1, "p6-enforce-handoff"),
    )
    handoff = _run_check(plan_dir, status_file, capsys)

    assert handoff["action"] == "handoff_required"
    assert handoff["reason"] == "threshold"
    assert "p6-enforce-handoff" in handoff["resume_prompt"]
    ledger = json.loads(
        (plan_dir / "notes" / "token-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["p6-enforce-handoff"]["cumulative_tokens"] == 7_500

    confirmed = fastpath.run(
        [
            "hook",
            "pipeline-handoff-complete",
            "--harness",
            "paseo",
            "--session",
            "paseo-agent-1",
            "--turn",
            "1",
            "--plan-dir",
            str(plan_dir),
            "--slot",
            "builder-1",
        ]
    )
    assert confirmed == 0
    assert json.loads(capsys.readouterr().out) == {"completed": True, "turn": 1}

    handed_off = _slot(plan_dir)
    assert handed_off.state == "handed_off"
    assert json.loads(handed_off.checkpoint or "{}")["turn"] == 1

    retired = _run_check(plan_dir, status_file, capsys)
    assert retired["action"] == "handoff_completed"


def test_replaced_agent_cannot_heartbeat_the_slot(tmp_path: Path, capsys) -> None:
    plan_dir = _store_plan(tmp_path)
    status_file = tmp_path / "status.json"

    _run_check(plan_dir, status_file, capsys, status=_status(tokens=1_000))
    _slots(plan_dir).replace("builder-1", new_agent_ref="paseo-agent-2", actor="test")

    zombie = _run_check(
        plan_dir,
        status_file,
        capsys,
        status=_status(cursor="turn-2", tokens=2_000),
    )

    assert zombie["action"] == "checkpoint_required"
    recorded = _slot(plan_dir)
    assert recorded.agent_ref == "paseo-agent-2"
    assert recorded.turn_count == 1
    assert recorded.context_tokens == 1_000


def test_slot_owned_by_another_agent_is_left_alone(tmp_path: Path, capsys) -> None:
    plan_dir = _store_plan(tmp_path)
    status_file = tmp_path / "status.json"
    _slots(plan_dir).register(
        "builder-1", plan_id="plan", role="builder", agent_ref="other-agent"
    )

    result = _run_check(plan_dir, status_file, capsys, status=_status(tokens=1_000))

    assert result["action"] == "checkpoint_required"
    recorded = _slot(plan_dir)
    assert recorded.agent_ref == "other-agent"
    assert recorded.turn_count == 0
    assert recorded.context_tokens is None


def test_paseo_slot_without_countable_status_requires_one_shot(
    tmp_path: Path,
) -> None:
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")

    result = handoff_checkpoint.check_paseo_slot(
        plan_dir,
        "builder-1",
        "builder",
        "item-1",
        {"agentId": "paseo-agent-1", "contextWindowUsedTokens": 10},
    )

    assert result["action"] == "one_shot_required"
