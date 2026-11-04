from __future__ import annotations

import json
import sqlite3

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_workflow import cli


def _working_store(tmp_path, monkeypatch) -> None:
    working = tmp_path / "memory"
    initialize(working)
    database = working / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    plan = working / "plans" / "demo" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nid: demo\n---\n\n# Demo\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(tmp_path)


def test_handoff_checkpoint_resume_fences_old_epoch(tmp_path, monkeypatch, capsys):
    _working_store(tmp_path, monkeypatch)
    assert (
        cli.run(
            [
                "plan",
                "slot",
                "register",
                "demo-worker",
                "--plan",
                "demo",
                "--role",
                "worker",
                "--agent-ref",
                "agent-1",
            ]
        )
        == 0
    )
    assert cli.run(["plan", "slot", "handoff", "demo-worker", "--epoch", "1"]) == 0

    checkpoint_dir = tmp_path / "memory/plans/demo/notes/checkpoints/demo-worker"
    record = json.loads(
        (checkpoint_dir / "checkpoint.json").read_text(encoding="utf-8")
    )
    markdown = (checkpoint_dir / "checkpoint.md").read_text(encoding="utf-8")
    assert record["slot"]["slot_id"] == "demo-worker"
    assert "Do not redo:" in markdown

    assert (
        cli.run(["plan", "slot", "resume", "demo-worker", "--agent-ref", "agent-2"])
        == 0
    )
    assert "epoch 1" in capsys.readouterr().out
    assert cli.run(["plan", "slot", "heartbeat", "demo-worker", "--epoch", "1"]) == 1
    assert "stale" in capsys.readouterr().err


def test_slot_help_snapshots_are_registered():
    assert "handoff" in cli.help_text("plan slot")
    assert "resume" in cli.help_text("plan slot", short=True)


def test_stale_handoff_leaves_checkpoint_files_and_store_untouched(
    tmp_path, monkeypatch, capsys
):
    _working_store(tmp_path, monkeypatch)
    assert (
        cli.run(
            [
                "plan",
                "slot",
                "register",
                "demo-worker",
                "--plan",
                "demo",
                "--role",
                "worker",
                "--agent-ref",
                "agent-1",
            ]
        )
        == 0
    )
    assert cli.run(["plan", "slot", "handoff", "demo-worker", "--epoch", "1"]) == 0

    working = tmp_path / "memory"
    checkpoint_dir = working / "plans/demo/notes/checkpoints/demo-worker"
    json_path = checkpoint_dir / "checkpoint.json"
    markdown_path = checkpoint_dir / "checkpoint.md"
    old_json = json_path.read_bytes()
    old_markdown = markdown_path.read_bytes()

    from varde_workflow.commands import slot as slot_command

    original_open_data = slot_command.open_data

    def open_data_with_racing_handoff(working_dir, config):
        data = original_open_data(working_dir, config)
        original_handoff = data.slots.handoff

        def replace_before_handoff(slot_id, *, epoch, checkpoint, now=None):
            open_data(working_dir, load_data_config()).slots.replace(
                slot_id, new_agent_ref="agent-2", actor="test"
            )
            return original_handoff(
                slot_id, epoch=epoch, checkpoint=checkpoint, now=now
            )

        data.slots.handoff = replace_before_handoff
        return data

    monkeypatch.setattr(slot_command, "open_data", open_data_with_racing_handoff)
    assert cli.run(["plan", "slot", "handoff", "demo-worker", "--epoch", "1"]) == 1
    assert "stale" in capsys.readouterr().err

    assert json_path.read_bytes() == old_json
    assert markdown_path.read_bytes() == old_markdown
    assert sorted(path.name for path in checkpoint_dir.iterdir()) == [
        "checkpoint.json",
        "checkpoint.md",
    ]
    slot = open_data(working, load_data_config()).slots.show("demo-worker")
    assert json.loads(slot.checkpoint) == json.loads(old_json)
    assert slot.epoch == 2
    assert slot.state == "active"
