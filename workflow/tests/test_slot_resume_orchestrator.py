from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.plan_state import open_plan_state
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_workflow import cli
from varde_workflow.slot_handoff_render import render_handoff

ORCHESTRATOR = "demo-orchestrator"
CHILDREN = (
    ("demo-builder", "builder", "agent-builder"),
    ("demo-reviewer", "reviewer", "agent-reviewer"),
    ("demo-planner", "planner", "agent-planner"),
)
ITEM_IDS = ("task-1", "task-2", "task-3", "task-4")


def _working_store(tmp_path, monkeypatch) -> tuple[Path, Path]:
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
    return working, database


def _register_slots() -> None:
    for slot, role, agent_ref in (
        (ORCHESTRATOR, "orchestrator", "agent-orchestrator"),
        *CHILDREN,
    ):
        assert (
            cli.run(
                [
                    "plan",
                    "slot",
                    "register",
                    slot,
                    "--plan",
                    "demo",
                    "--role",
                    role,
                    "--agent-ref",
                    agent_ref,
                ]
            )
            == 0
        )


def _claim_items(working: Path) -> None:
    plan_dir = str((working / "plans" / "demo").resolve())
    data = open_data(working, load_data_config())
    for item_id in ITEM_IDS:
        data.queue.enqueue(QueueItemInput(item_id, plan_dir, queue_name="build"))
    owners = [
        CHILDREN[0][0],
        CHILDREN[0][0],
        CHILDREN[1][0],
        CHILDREN[2][0],
    ]
    for owner in owners:
        assert (
            data.slots.claim(owner, epoch=1, queue_name="build", lease_s=300)
            is not None
        )


def test_orchestrator_resume_keeps_state_children_and_claims(
    tmp_path, monkeypatch, capsys
):
    working, database = _working_store(tmp_path, monkeypatch)
    _register_slots()
    _claim_items(working)

    plan_dir = str((working / "plans" / "demo").resolve())
    plan_state = open_plan_state(database.parents[2])
    plan_state.set_plan_state(
        plan_dir, status="building", owner=ORCHESTRATOR, assigned_to=ORCHESTRATOR
    )
    data = open_data(working, load_data_config())
    before_state = plan_state.plan_state(plan_dir)
    before_children = {slot: data.slots.show(slot) for slot, _, _ in CHILDREN}
    before_claims = {slot: data.slots.claimed(slot) for slot, _, _ in CHILDREN}
    assert sum(len(claims) for claims in before_claims.values()) == len(ITEM_IDS)

    assert (
        cli.run(
            [
                "plan",
                "slot",
                "resume",
                ORCHESTRATOR,
                "--agent-ref",
                "agent-orchestrator-2",
            ]
        )
        == 0
    )
    prompt = capsys.readouterr().out

    assert plan_state.plan_state(plan_dir) == before_state
    for slot, _, _ in CHILDREN:
        assert data.slots.show(slot) == before_children[slot]
        assert data.slots.claimed(slot) == before_claims[slot]
        assert slot in prompt
    for claims in before_claims.values():
        for item in claims:
            assert item.id in prompt

    replaced = data.slots.show(ORCHESTRATOR)
    assert replaced.epoch == 2
    assert replaced.agent_ref == "agent-orchestrator-2"
    assert replaced.state == "active"

    assert cli.run(["plan", "slot", "heartbeat", ORCHESTRATOR, "--epoch", "1"]) == 1
    assert "stale" in capsys.readouterr().err
    assert cli.run(["plan", "slot", "heartbeat", ORCHESTRATOR, "--epoch", "2"]) == 0


def _record_with_children(children: int, claims: int) -> dict[str, object]:
    return {
        "role": "orchestrator",
        "slot": {"slot_id": ORCHESTRATOR, "state": "active", "turn_count": 2},
        "plan_id": "demo",
        "epoch": 2,
        "claimed_items": [],
        "child_slots": [
            {
                "slot": {
                    "slot_id": f"child-{index:02d}",
                    "epoch": 1,
                    "state": "active",
                },
                "claimed_items": [
                    {"id": f"item-{index:02d}-{claim:02d}"}
                    for claim in range(1, claims + 1)
                ],
            }
            for index in range(1, children + 1)
        ],
        "last_progress": {},
        "context_tokens": None,
        "recent_events": [],
        "task_states": [],
        "next_actions": ["Continue child work"],
    }


def test_resume_prompt_caps_child_slots_and_claims():
    rendered = render_handoff(_record_with_children(children=10, claims=10))
    prompt = rendered.resume_prompt

    assert "child-08" in prompt
    assert "child-09" not in prompt
    assert "child-10" not in prompt
    assert "and 2 more child slots" in prompt
    assert "item-01-08" in prompt
    assert "item-01-09" not in prompt
    assert "and 2 more claims" in prompt
    assert "child-09" not in rendered.markdown
    assert "item-01-09" not in rendered.markdown
