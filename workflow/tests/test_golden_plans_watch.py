from __future__ import annotations

import contextlib
import io
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from varde_workflow.commands import status, watch

sys.path.insert(0, str(Path(__file__).parent))
from golden.plans.builder import (
    ASSIGNED_COMMIT_AT,
    ASSIGNED_PLAN_MTIME,
    ASSIGNED_STATUS_AT,
    ASSIGNED_TASK_MTIME,
    FIXED_CLOCK,
    build,
    check_snapshot,
)


def _snapshot(
    working: Path,
    repo: Path,
    monkeypatch,
    *,
    clock: float = FIXED_CLOCK,
    stale: int = 1200,
) -> str:
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    monkeypatch.setattr(status.time, "time", lambda: clock)
    output = io.StringIO()
    args = Namespace(
        working=working,
        repo=repo,
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=stale,
        notes=None,
        json=True,
        interval=60,
    )
    with contextlib.redirect_stdout(output):
        assert watch.run_watch(args, clock=lambda: clock) == 0
    return output.getvalue()


@pytest.mark.parametrize("timezone", ["UTC", "Europe/Oslo"])
def test_plan_watch_goldens_are_stable(
    tmp_path: Path, monkeypatch, timezone: str
) -> None:
    assert (
        ASSIGNED_PLAN_MTIME
        < ASSIGNED_TASK_MTIME
        < ASSIGNED_STATUS_AT
        < ASSIGNED_COMMIT_AT
        < FIXED_CLOCK
    )
    monkeypatch.setenv("TZ", timezone)
    working, repo = build(tmp_path)
    inbox = working / ".cache/inbox/messages.jsonl"
    messages = inbox.read_text(encoding="utf-8")
    inbox.unlink()
    without_inbox = _snapshot(working, repo, monkeypatch)
    check_snapshot("plans-watch", without_inbox, tmp_path)
    inbox.write_text(messages, encoding="utf-8")
    with_inbox = _snapshot(working, repo, monkeypatch)
    check_snapshot("plans-watch-inbox", with_inbox, tmp_path)
    inbox.unlink()
    stalled = _snapshot(working, repo, monkeypatch, clock=FIXED_CLOCK + 700, stale=600)
    check_snapshot("plans-watch-stalled", stalled, tmp_path)

    plain = json.loads(without_inbox)["plans"]
    inboxed = json.loads(with_inbox)["plans"]
    stalled_plans = json.loads(stalled)["plans"]
    assert any(plan["id"] == "assigned" for plan in plain)
    assigned = next(plan for plan in inboxed if plan["id"] == "assigned")
    assert assigned["awaiting_user"] == "Please approve the assigned plan."
    stalled_assigned = next(plan for plan in stalled_plans if plan["id"] == "assigned")
    assert stalled_assigned["stalled"] is True
    assert stalled_assigned["state"] == "blocked"
    assert stalled_assigned["detail"] == (
        "stalled; idle 11m with open work and no hand-back"
    )
    assert stalled_assigned["newest_activity"] == 1_700_000_040.0
