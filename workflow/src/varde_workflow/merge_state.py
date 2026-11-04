"""Read-only checks for whether a plan branch is integrated into its base."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.views import (
    Binding,
    StatusFacts,
    classify_status,
)
from varde_data.views import (
    awaiting_user_message as view_awaiting_user_message,
)
from varde_data.views import (
    json_merge_state as view_json_merge_state,
)
from varde_data.views import (
    stalled_detail as view_stalled_detail,
)
from varde_learn.knowledge.frontmatter import parse

from varde_workflow.execution_wave_tools import git

APPROVED_MERGE_GRACE_SECONDS = 15 * 60


def branch_exists(repo: Path, branch: str) -> bool:
    result = git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    return result is not None and result[0] == 0


def local_branches(repo: Path) -> frozenset[str]:
    """List local branch names with one git call."""
    result = git(repo, ["for-each-ref", "--format=%(refname)", "refs/heads"])
    if result is None or result[0] != 0:
        return frozenset()
    prefix = "refs/heads/"
    return frozenset(
        line.removeprefix(prefix) for line in result[1].splitlines() if line
    )


def is_merged(repo: Path, branch: str, base: str = "main") -> bool:
    if not branch_exists(repo, branch):
        return False
    result = git(repo, ["merge-base", "--is-ancestor", branch, base])
    return result is not None and result[0] == 0


def json_merge_state(
    record: dict[str, Any],
    repo: Path,
    existing: frozenset[str] | None = None,
    merged_facts: frozenset[str] | None = None,
) -> str:
    """Classify the plan's approved branch for status and watch JSON.

    Pass `existing` (from `local_branches`) when classifying many plans.
    """
    if not record.get("merge_approved_at"):
        return view_json_merge_state(record, StatusFacts(0.0))
    branch = record.get("branch") or f"worktree/{record['id']}"
    exists = isinstance(branch, str) and (
        branch in existing if existing is not None else branch_exists(repo, branch)
    )
    branches = {branch: 0.0} if exists else {}
    merged = (
        frozenset({branch})
        if branches
        and (
            branch in merged_facts
            if merged_facts is not None
            else is_merged(repo, branch)
        )
        else frozenset()
    )
    return view_json_merge_state(
        record, StatusFacts(0.0, branches=branches, merged=merged)
    )


def read_bindings(working: Path) -> list[dict[str, Any]]:
    """Read current orchestrator bindings for plan status checks."""
    try:
        rows = open_data(working, load_data_config()).addresses.list_bindings()
    except OSError:
        return []
    return [
        {
            "address": item.address,
            "session_id": item.session_id,
            "harness": item.harness,
            "bound_at": item.bound_at.isoformat(),
            "last_seen": item.last_seen.isoformat(),
            "token_id": item.token_id,
            **item.extra,
        }
        for item in rows
    ]


def awaiting_user_message(
    record: dict[str, Any], messages: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the latest unanswered request, using append-only inbox order."""
    pending = view_awaiting_user_message(record, tuple(messages))
    return dict(pending) if pending is not None else None


def awaiting_user(record: dict[str, Any], working: Path) -> str | None:
    """Read the inbox and return the reason an assigned plan awaits the user."""
    if (
        not record.get("assigned_to")
        or classify_status(str(record.get("status", ""))) == "terminal"
    ):
        return None
    messages = [
        _message_dict(message)
        for message in open_data(working, load_data_config())
        .messages.read_all()
        .records
    ]
    pending = awaiting_user_message(record, messages)
    if pending is None:
        return None
    notes = pending.get("notes")
    if isinstance(notes, str) and notes:
        try:
            decision = json.loads(Path(notes).read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            pass
        else:
            title = decision.get("title") if isinstance(decision, dict) else None
            if isinstance(title, str) and title:
                return title
    text = pending.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return "Waiting on your decision"


def read_plan_tasks(plan_dir: Path) -> list[dict[str, Any]]:
    """Read task metadata used by watch and stalled-plan status."""
    try:
        paths = sorted((plan_dir / "tasks").glob("*.md"))
    except OSError:
        return []
    tasks = []
    for path in paths:
        try:
            mapping, _ = parse(path.read_bytes())
        except OSError, ValueError:
            continue
        if mapping.get("artifact_type", mapping.get("type", "plan")) != "task":
            continue
        depends = mapping.get("depends_on", [])
        if isinstance(depends, str):
            depends = [depends]
        task_id = mapping.get("id")
        task_status = mapping.get("status", "todo")
        tasks.append(
            {
                "id": task_id if isinstance(task_id, str) and task_id else path.stem,
                "stem": path.stem,
                "status": task_status if isinstance(task_status, str) else "todo",
                "status_at": mapping.get("status_at")
                if isinstance(mapping.get("status_at"), str)
                else None,
                "depends": [item for item in depends if isinstance(item, str)]
                if isinstance(depends, list)
                else [],
            }
        )
    return tasks


def stalled_detail(
    record: dict[str, Any],
    tasks: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    working: Path,
    now: float,
    messages: list[Mapping[str, object]] | None = None,
) -> str | None:
    """Describe an assigned plan idle with open work and no owner hand-back.

    Pass `messages` (from `read_messages`) when judging many plans so the log is
    read once, not per plan.
    """
    if messages is None:
        messages = read_messages(working)
    facts = StatusFacts(
        now,
        bindings=tuple(
            Binding(
                str(item.get("address", "")),
                item.get("plan_id") if isinstance(item.get("plan_id"), str) else None,
                item.get("branch") if isinstance(item.get("branch"), str) else None,
                item.get("last_seen")
                if isinstance(item.get("last_seen"), str)
                else None,
            )
            for item in bindings
            if isinstance(item.get("address"), str)
        ),
    )
    return view_stalled_detail(record, tuple(tasks), tuple(messages), facts)


def read_messages(working: Path) -> list[Mapping[str, object]]:
    return [
        _message_dict(message)
        for message in open_data(working, load_data_config())
        .messages.read_all()
        .records
    ]


def _message_dict(message) -> dict[str, Any]:
    return {
        "id": message.id,
        "ts": message.ts,
        "from": message.from_,
        "to": message.to,
        "kind": message.kind,
        "text": message.text,
        "notes": message.notes,
    }
