"""Manage durable worker and orchestrator slots."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.errors import Conflict, DataError
from varde_data.locking import atomic_write
from varde_data.open import open_data
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.now import resolve_plan
from varde_workflow.handoff_format import validate
from varde_workflow.slot_handoff_render import render_handoff


def run(args: Any) -> int:
    """Run a slot command and report data conflicts with stable exit codes."""
    working = MemoryPaths.resolve(Path.cwd()).working.path
    try:
        data = open_data(working, load_data_config())
        result = _run_action(args, data.slots, working)
    except (DataError, OSError, ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    elif isinstance(result, str):
        print(result)
    else:
        print(
            json.dumps(
                result, ensure_ascii=False, indent=2, sort_keys=True, default=str
            )
        )
    return 0


def _run_action(args: Any, slots: Any, working: Path) -> dict[str, object] | str:
    action = args.slot_action
    if action == "register":
        cwd = Path.cwd()
        plans = working / "plans"
        plan_path = resolve_plan(args.plan, cwd, plans)
        from varde_learn.knowledge.frontmatter import parse

        metadata, _ = parse(plan_path.read_bytes())
        plan_id = metadata.get("id")
        if not isinstance(plan_id, str):
            plan_id = plan_path.parent.name
        return asdict(
            slots.register(
                args.slot,
                plan_id=plan_id,
                role=args.role,
                agent_ref=args.agent_ref,
                session_id=args.session_id,
                lease_s=args.lease,
            )
        )
    if action == "heartbeat":
        return asdict(
            slots.heartbeat(
                args.slot,
                epoch=args.epoch,
                progress_note=args.progress,
                context_tokens=args.context_tokens,
                turn_count=args.turn_count,
                lease_s=args.lease,
            )
        )
    if action == "show":
        return asdict(slots.show(args.slot))
    if action == "park":
        return asdict(slots.park(args.slot, epoch=args.epoch))
    if action == "unpark":
        return asdict(slots.unpark(args.slot, epoch=args.epoch))
    if action == "handoff":
        return _handoff(slots, args.slot, args.epoch, working)
    if action == "resume":
        return _resume(slots, args, working)
    if action == "reclaim":
        return asdict(slots.reclaim_stale())
    raise ValueError(f"unknown slot action: {action}")


def _handoff(slots: Any, slot_id: str, epoch: int, working: Path) -> dict[str, object]:
    slot = slots.show(slot_id)
    if slot.epoch != epoch or slot.state == "dead":
        raise Conflict(f"slot {slot_id} epoch or state is stale")
    rendering = render_handoff(slots.handoff_record(slot_id))
    result = validate(rendering.markdown, lambda value: (working / value).exists())
    if result.errors:
        raise ValueError("invalid handoff: " + "; ".join(result.errors))
    plan_path = resolve_plan(slot.plan_id, Path.cwd(), working / "plans")
    checkpoint_dir = plan_path.parent / "notes" / "checkpoints" / slot_id
    checkpoint_json = json.dumps(
        rendering.record, ensure_ascii=False, sort_keys=True, indent=2
    )
    # The repository handoff is the epoch fence: a stale handoff raises Conflict
    # before any file write, so it cannot overwrite the replacement's checkpoint.
    # The writes below are atomic (temp file plus rename) and follow the fence.
    slots.handoff(slot_id, epoch=epoch, checkpoint=checkpoint_json)
    atomic_write(
        checkpoint_dir / "checkpoint.json", checkpoint_json.encode("utf-8"), mode=0o600
    )
    atomic_write(
        checkpoint_dir / "checkpoint.md", rendering.markdown.encode("utf-8"), mode=0o600
    )
    return {
        "slot": slot_id,
        "epoch": epoch,
        "checkpoint": str(checkpoint_dir),
        "validation": "passed",
    }


def _resume(slots: Any, args: Any, working: Path) -> str:
    slot = slots.show(args.slot)
    slots.replace(
        args.slot,
        new_agent_ref=args.agent_ref,
        new_session_id=args.session_id,
        lease_s=args.lease,
        actor=args.agent_ref,
    )
    if slot.checkpoint:
        record = json.loads(slot.checkpoint)
        prompt = render_handoff(record).resume_prompt
    else:
        # A crash leaves no checkpoint; build the prompt from durable state so
        # the replacement still learns the plan's child slots and their claims.
        prompt = render_handoff(slots.handoff_record(args.slot)).resume_prompt
    return prompt
