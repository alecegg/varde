"""Read merge approval records from the runner.

The runner records user, main, and guard approvals. Agent records are trusted only
when their checklist matches the plan's reviewed commit.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote

DEFAULT_RUNNER_PORT = 8765
USER = "user"
TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class Approval:
    plan_id: str
    approved_at: str
    commit_sha: str | None = None
    approver_kind: str = USER


class ApprovalUnavailable(OSError):
    """The runner could not be asked for the record."""


def runner_port(env: Mapping[str, str]) -> int:
    raw = env.get("VARDE_RUNNER_PORT", "")
    return int(raw) if raw.isdigit() else DEFAULT_RUNNER_PORT


def require_approval(plan_id: str, reviewed_commit: str) -> Approval:
    """A valid approval for a plan, or a `CliError` saying it is missing."""
    from varde_workflow.commands.error import CliError

    approval = fetch_approval(plan_id, reviewed_commit)
    if approval is None:
        raise CliError(
            f"no merge approval is recorded for {plan_id}; "
            "the user approves it in the dashboard Mailbox"
        )
    return approval


def parse_approval(body: Any, reviewed_commit: str) -> Approval | None:  # noqa: PLR0911 - malformed records fail at validation boundaries.
    """Accept user records, or checked main/guard records tied to the review."""
    record = body.get("approval") if isinstance(body, dict) else None
    if not isinstance(record, dict):
        return None
    kind = record.get("approver_kind", USER)
    commit_sha = record.get("commit_sha")
    if record.get("approved_by") == USER and kind == USER:
        if record.get("key_kind") == "branch" and not isinstance(commit_sha, str):
            return None
    elif kind in {"main", "guard"} and record.get("approved_by") == kind:
        checklist = record.get("checklist")
        if not isinstance(checklist, dict) or not reviewed_commit:
            return None
        required = ("plan_followed", "review_commit", "gate_result", "abnormal_events")
        if any(field not in checklist for field in required):
            return None
        if (
            checklist.get("plan_followed") is not True
            or checklist.get("review_commit") != reviewed_commit
            or commit_sha != reviewed_commit
        ):
            return None
        if any(
            not isinstance(checklist.get(field), str) or not checklist[field].strip()
            for field in required[1:]
        ):
            return None
    else:
        return None
    plan_id, approved_at = record.get("plan_id"), record.get("approved_at")
    if not isinstance(plan_id, str) or not isinstance(approved_at, str):
        return None
    return Approval(
        plan_id,
        approved_at,
        commit_sha if isinstance(commit_sha, str) else None,
        str(kind),
    )


def fetch_approval(
    plan_id: str, reviewed_commit: str, port: int | None = None
) -> Approval | None:
    """The latest user approval for a plan; raises `ApprovalUnavailable`."""
    use_port = port if port is not None else runner_port(os.environ)
    path = f"/api/plans/{quote(plan_id, safe='')}/merge-approval"
    url = f"http://127.0.0.1:{use_port}{path}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=TIMEOUT_SECONDS) as response:
            return parse_approval(json.load(response), reviewed_commit)
    except (URLError, ValueError, TimeoutError) as exc:
        raise ApprovalUnavailable(f"merge approval record unavailable: {exc}") from exc


def plan_identity(metadata: dict[str, Any], default_id: str) -> tuple[str, str]:
    identifier = metadata.get("id", default_id)
    branch = metadata.get("branch") or f"worktree/{identifier}"
    if not isinstance(branch, str) or not branch:
        raise ValueError("plan branch must be a non-empty string")
    return str(identifier), branch


def unapproved_decision(plan_id: str, branch: str) -> dict[str, Any]:
    question = f"{branch} merged into main with no recorded approval"
    return {
        "type": "question",
        "asked": question,
        "why": "No user approval record exists, so the merge skipped the gate.",
        "options": [{"id": "ack", "label": "Acknowledge"}],
        "recommendation": "ack",
        "plan_id": plan_id,
        "question": question,
    }


def raise_unapproved_item(working: Path, plan_id: str, branch: str) -> bool:
    """Post one Mailbox item for the plan; False when it was already posted."""
    from varde_workflow.inbox import append_message, read_all

    notes = working / ".cache" / "merge-gate" / f"{plan_id}-unapproved.json"
    if any(message.notes == str(notes) for message in read_all(working)):
        return False
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(json.dumps(unapproved_decision(plan_id, branch)), encoding="utf-8")
    append_message(
        "merge-gate",
        "main",
        "needs-user",
        f"{branch} merged without a recorded approval",
        notes,
        working=working,
    )
    return True
