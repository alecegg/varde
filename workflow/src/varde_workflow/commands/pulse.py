"""Read-only batched plan progress and orchestration facts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands import status, watch
from varde_workflow.commands.now import read_line, read_plan_id, resolve_plan
from varde_workflow.commands.watch_cache import cache_path_for_repo, read_for_repo
from varde_workflow.execution_wave_tools import git
from varde_workflow.pulse_facts import fingerprint_facts, is_idle, merge_state
from varde_workflow.pulse_mail import mailman_status, unread_count

DEFAULT_STALE_SECONDS = 1200
FILE_PATTERNS = ("decision-*.json", "merge-decision.json", "HANDOFF.md")


def _state_path(working: Path, repo: Path) -> Path:
    watch_path = cache_path_for_repo(working, None, repo)
    return watch_path.with_name(watch_path.name.replace("plan-watch-", "plan-pulse-"))


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    plans = value.get("plans", {}) if isinstance(value, dict) else {}
    return plans if isinstance(plans, dict) else {}


def _write_state(path: Path, plans: dict[str, Any]) -> None:
    data = (json.dumps({"plans": plans}, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _group_events(events: list[Any]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for event in events:
        grouped[event.plan].append(event.to_json())
    return dict(grouped)


def _task_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    total = int(snapshot.get("total", 0))
    done = int(snapshot.get("done", 0))
    blocked = len(snapshot.get("blocked_tasks", []))
    return {
        "blocked": blocked,
        "done": done,
        "open": max(0, total - done - blocked),
    }


def _collect_files(plan_dir: Path) -> dict[str, float]:
    found = {}
    notes = plan_dir / "notes"
    for pattern in FILE_PATTERNS:
        for path in sorted(notes.glob(pattern)):
            try:
                found[path.relative_to(plan_dir).as_posix()] = path.stat().st_mtime
            except OSError:
                continue
    return found


def _changed_files(
    current: dict[str, float], previous: dict[str, Any]
) -> list[dict[str, str]]:
    return [
        {
            "path": name,
            "mtime": datetime.fromtimestamp(modified, UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        for name, modified in sorted(current.items())
        if previous.get(name) != modified
    ]


def _worktree(path_value: Any) -> dict[str, Any] | None:
    if not isinstance(path_value, str) or not Path(path_value).is_dir():
        return None
    path = Path(path_value)
    status_result = git(path, ["status", "--short", "--branch"])
    log_result = git(path, ["log", "-1", "--format=%h%x1f%s"])
    if status_result is None or status_result[0] != 0:
        return None
    status_lines = status_result[1].splitlines()
    header = status_lines[0] if status_lines else ""
    branch = header.removeprefix("## ").split("...", 1)[0]
    head = subject = None
    if log_result is not None and log_result[0] == 0:
        head, _, subject = log_result[1].strip().partition("\x1f")
    return {
        "branch": branch or None,
        "head": head,
        "subject": subject,
        "dirty": max(0, len(status_lines) - 1),
    }


def _plan_facts(
    snapshot: dict[str, Any],
    plan_dir: Path,
    inbox: Path,
    previous: dict[str, Any],
    events: list[dict[str, str]],
) -> dict[str, Any]:
    owner = snapshot.get("assigned_to") or snapshot.get("owner")
    current_files = _collect_files(plan_dir)
    return {
        "id": snapshot["id"],
        "status": snapshot["status"],
        "tasks": _task_counts(snapshot),
        "now": snapshot.get("now_line"),
        "owner": owner,
        "unread": unread_count(inbox, owner) if isinstance(owner, str) else None,
        "files": _changed_files(current_files, previous.get("files", {})),
        "_all_files": current_files,
        "worktree": _worktree(snapshot.get("worktree")),
        "events": events,
    }


def _plan_dir(plans_dir: Path, plan_id: str) -> Path:
    direct = plans_dir / plan_id
    if (direct / "plan.md").is_file():
        return direct
    return next(
        path.parent
        for path in plans_dir.rglob("plan.md")
        if path.parent.name == plan_id
    )


def _selected_snapshots(
    argument: str | None,
    cwd: Path,
    plans_dir: Path,
    snapshots: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], Path]], bool]:
    if argument is None:
        selected = []
        for item in snapshots:
            if status.status_bucket(item["status"]) in {"terminal", "backlog"}:
                continue
            selected.append((item, _plan_dir(plans_dir, str(item["id"]))))
        return selected, True

    path = resolve_plan(argument, cwd, plans_dir)
    plan_id = read_plan_id(path)
    snapshot = next((item for item in snapshots if item["id"] == plan_id), None)
    if snapshot is None:
        record = status.read_plan(path, 60)
        if record is None:
            raise ValueError(f"unreadable plan `{argument}`")
        snapshot = {
            "id": plan_id,
            "status": record["status"],
            "owner": record.get("owner"),
            "assigned_to": record.get("assigned_to"),
            "now_line": read_line(plans_dir, path),
            "done": record.get("done", 0),
            "total": record.get("total", 0),
            "blocked_tasks": [],
            "worktree": None,
        }
    return [(snapshot, path.parent)], False


def _cache_events(
    snapshots: list[dict[str, Any]], working: Path, repo: Path, timestamp: float
) -> dict[str, list[dict[str, str]]]:
    cache = read_for_repo(working, None, repo)
    events, _ = watch.frame_events(
        snapshots, timestamp, DEFAULT_STALE_SECONDS, cache, seed=False
    )
    return _group_events(events)


def _fingerprints(facts: list[dict[str, Any]]) -> dict[str, str]:
    return {plan["id"]: fingerprint_facts(plan) for plan in facts}


def _updated_state(
    previous: dict[str, Any],
    facts: list[dict[str, Any]],
    fingerprints: dict[str, str],
    *,
    full_scan: bool,
) -> dict[str, Any]:
    updates = {
        plan["id"]: {
            "fingerprint": fingerprints[plan["id"]],
            "files": plan["_all_files"],
        }
        for plan in facts
    }
    retained = {plan["id"] for plan in facts} if full_scan else None
    return merge_state(previous, updates, retained)


def _display_facts(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "_all_files"}


def _render(plan: dict[str, Any]) -> str:
    counts = ", ".join(f"{key}={value}" for key, value in plan["tasks"].items())
    line = (
        f"{plan['id']}: {plan['status']} tasks {counts}; "
        f"now: {plan['now'] or 'none'}; owner: {plan['owner'] or 'none'}"
    )
    if plan["unread"] is not None:
        line += f"; unread: {plan['unread']}"
    if plan["files"]:
        line += "; files: " + ", ".join(
            f"{item['path']} ({item['mtime']})" for item in plan["files"]
        )
    if plan["worktree"]:
        worktree = plan["worktree"]
        details = [worktree["branch"] or "none", worktree["head"] or "none"]
        if worktree["subject"]:
            details.append(worktree["subject"])
        line += f"; worktree: {' '.join(details)} dirty={worktree['dirty']}"
    if plan["events"]:
        descriptions = [
            f"{event['kind']} {event.get('detail', '')}".rstrip()
            for event in plan["events"]
        ]
        line += "; events: " + "; ".join(descriptions)
    return line


def _print_text(
    facts: list[dict[str, Any]],
    current: dict[str, str],
    previous: dict[str, Any],
    idle: bool,
    mailman: str,
) -> None:
    if idle:
        print(f"pulse: idle ({len(facts)} plans)")
    else:
        for plan in facts:
            prior = previous.get(plan["id"], {})
            unchanged = (
                isinstance(prior, dict)
                and prior.get("fingerprint") == current[plan["id"]]
            )
            print(f"{plan['id']}: no change" if unchanged else _render(plan))
    if mailman != "alive":
        print(f"mail: {mailman}")


def run(args: Any) -> int:
    cwd = Path.cwd()
    working = MemoryPaths.resolve(cwd).working.path
    plans_dir = working / "plans"
    repo = cwd
    state_path = _state_path(working, repo)
    previous = _read_state(state_path)
    try:
        timestamp = time.time()
        snapshots = watch.scan(working, repo, timestamp, DEFAULT_STALE_SECONDS)
        selected, full_scan = _selected_snapshots(
            getattr(args, "plan", None), cwd, plans_dir, snapshots
        )
        events_by_plan = _cache_events(snapshots, working, repo, timestamp)
        inbox = working / ".cache" / "inbox"
        facts = [
            _plan_facts(
                snapshot,
                plan_dir,
                inbox,
                previous.get(snapshot["id"], {}),
                events_by_plan.get(snapshot["id"], []),
            )
            for snapshot, plan_dir in selected
        ]
    except (OSError, ValueError, TypeError, StopIteration) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 70

    current = _fingerprints(facts)
    old = {
        key: value.get("fingerprint", "") if isinstance(value, dict) else ""
        for key, value in previous.items()
    }
    idle = is_idle(current, old)
    _write_state(
        state_path,
        _updated_state(previous, facts, current, full_scan=full_scan),
    )
    mailman = mailman_status(working, datetime.now(UTC))
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "plans": [_display_facts(plan) for plan in facts],
                    "idle": idle,
                    "mailman": mailman,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        _print_text(facts, current, previous, idle, mailman)
    return 0
