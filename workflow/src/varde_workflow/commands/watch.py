"""Deterministic frame production for plan watch."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from varde_core.decision_files import DECISION_FILE_TYPES
from varde_data.plans import open_fresh_plans
from varde_data.views.watch import (
    ActivityFacts,
    WatchFacts,
    WatchTransitionFacts,
    approved_merge_elapsed,
    idle_bucket,
    is_waiting_line,
    latest_activity,
    owner_message_after,
    plan_state,
    task_counts,
    waiting_is_live,
    whole_plan_waiting_on_blocked,
)
from varde_data.views.watch import (
    WatchEvent as Event,
)
from varde_data.views.watch import (
    approved_merge_detail as view_approved_merge_detail,
)
from varde_data.views.watch import (
    bound_branches as view_bound_branches,
)
from varde_data.views.watch import (
    watch_state_detail as view_watch_state_detail,
)
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.collector_facts import (
    CollectorFacts,
    awaiting_user_from_facts,
    gather_collector_facts,
)
from varde_workflow.collectors import collect_watch, frame_events
from varde_workflow.commands import status
from varde_workflow.commands.watch_cache import (
    WatchCache,
    read_for_repo,
    write_if_changed_for_repo,
)
from varde_workflow.execution_wave_tools import git
from varde_workflow.git_facts import GitFacts, get_git_facts
from varde_workflow.merge_state import (
    awaiting_user,
    branch_exists,
    is_merged,
    json_merge_state,
    read_bindings,
    read_plan_tasks,
    stalled_detail,
)
from varde_workflow.orphan_decisions import orphan_decisions


def fixture_frames(
    fixtures: Iterable[Iterable[dict[str, Any]]],
    *,
    limit: int,
    clock: Callable[[], float],
    threshold: int = 60,
) -> Iterator[tuple[float, list[Event]]]:
    """Yield at most the first `limit` fixture frames using the injected clock."""
    previous = WatchCache()
    for index, snapshot in enumerate(fixtures):
        if index >= max(0, limit):
            break
        now = clock()
        events, previous = frame_events(snapshot, now, threshold, previous)
        yield now, events


def scan(
    working: Path, repo: Path, now: float, threshold_secs: int = 1200
) -> list[dict[str, Any]]:
    """Classify plans from their status, tasks, questions, and latest file activity."""
    plans: list[dict[str, Any]] = []
    plans_dir = working / "plans"
    paths: list[Path] = []
    status.collect_plan_paths(plans_dir, paths, [0])
    by_id = {
        record["id"]: (path, record)
        for path in paths
        if path.name == "plan.md" and (record := status.read_plan(path, 60)) is not None
    }
    all_ids = set(by_id)
    branches = _read_branches(repo)
    worktrees = _read_worktrees(repo)
    bindings = read_bindings(working)
    for plan_id, (path, record) in sorted(by_id.items()):
        artifact_status = record["status"]
        bucket = status.status_bucket(artifact_status)
        if bucket == "backlog":
            continue
        tasks = read_plan_tasks(path.parent)
        newest, source = _latest_activity(
            working, plans_dir, path, record, tasks, all_ids, branches, worktrees
        )
        if newest is None:
            continue
        from varde_workflow.commands.now import read_line

        now_line = read_line(plans_dir, path)
        done, total, blocked = task_counts(tasks)
        questions = record.get("questions", 0)
        plan_age = (
            max(0, int(now - path.stat().st_mtime)) if bucket == "terminal" else None
        )
        state, detail, idle = plan_state(
            WatchFacts(
                now=now,
                threshold=threshold_secs,
                newest_activity=newest,
                activity_source=source,
                status=artifact_status,
                status_bucket=bucket,
                tasks=tuple(tasks),
                done=done,
                blocked=tuple(blocked),
                questions=questions,
                plan_age=plan_age,
                now_line=now_line,
                waiting_live=bool(
                    is_waiting_line(now_line)
                    and _waiting_is_live(working, plans_dir, path, now, threshold_secs)
                ),
            )
        )
        if state is None:
            continue
        state, detail, idle_no_handback = watch_state_detail(
            state,
            detail,
            record,
            repo,
            tasks,
            bindings,
            working,
            now,
            newest,
            idle,
        )
        json_state = _plan_json_state(record, repo, tasks, bindings, working, now)
        bucket_number = idle_bucket(state, idle, threshold_secs)
        plans.append(
            {
                "id": plan_id,
                "owner": record.get("owner"),
                "assigned_to": record.get("assigned_to"),
                "merge_approved_at": record.get("merge_approved_at"),
                **json_state,
                "status": artifact_status,
                "state": state,
                "detail": detail,
                **_plan_runtime_metadata(
                    path, record, tasks, all_ids, branches, worktrees
                ),
                "last_event_at": datetime.fromtimestamp(newest, UTC).isoformat(),
                "done": done,
                "total": total,
                "blocked_tasks": blocked,
                "open_questions": questions,
                "now_line": now_line,
                "now_at": _iso_timestamp(status._now_line_timestamp(plans_dir, path)),
                "newest_activity": newest,
                "idle_no_handback": idle_no_handback,
                "bucket": bucket_number,
            }
        )
    return plans


def _watch_now_key(plans_dir: str, path: str) -> str:
    relative = path.removeprefix(plans_dir + "/").rsplit("/", 1)[0]
    return "__".join(component.replace("_", "_u") for component in relative.split("/"))


def _plan_json_state(
    record: dict[str, Any],
    repo: Path,
    tasks: list[dict[str, str]],
    bindings: list[dict[str, Any]],
    working: Path,
    now: float,
    facts: GitFacts | None = None,
    collector_facts: CollectorFacts | None = None,
) -> dict[str, Any]:
    awaiting = (
        awaiting_user_from_facts(collector_facts, record)
        if collector_facts is not None
        else awaiting_user(record, working)
    )
    messages = (
        cast("list[Mapping[str, object]]", list(collector_facts.messages))
        if collector_facts is not None
        else None
    )
    return {
        "assigned_to": record.get("assigned_to"),
        "awaiting_user": awaiting,
        "merge_approved_at": record.get("merge_approved_at"),
        "merge_state": json_merge_state(
            record,
            repo,
            frozenset(facts.branches) if facts is not None else None,
            facts.merged if facts is not None else None,
        ),
        "stalled": stalled_detail(record, tasks, bindings, working, now, messages)
        is not None,
    }


def _branch_owners(
    plan_ids: set[str], branches: dict[str, float]
) -> dict[str, str | None]:
    ordered_ids = sorted(plan_ids, key=len, reverse=True)
    owners = {}
    for branch in branches:
        suffix = branch.removeprefix("worktree/")
        owners[branch] = next(
            (
                plan_id
                for plan_id in ordered_ids
                if suffix == plan_id or suffix.startswith(f"{plan_id}-")
            ),
            None,
        )
    return owners


def _indexed_bound_branches(
    record: dict[str, Any],
    tasks: list[dict[str, Any]],
    owners: dict[str, str | None],
) -> list[str]:
    plan_id = str(record["id"])
    prefix = f"worktree/{plan_id}-"
    exact = {f"worktree/{plan_id}", *(f"worktree/{task['id']}" for task in tasks)}
    branch = record.get("branch")
    if isinstance(branch, str) and branch:
        exact.add(branch)
    return sorted(
        name
        for name, owner in owners.items()
        if not (owner is not None and owner.startswith(f"{plan_id}-"))
        and (name in exact or (owner == plan_id and name.startswith(prefix)))
    )


def _decode_dependencies(value: object) -> object:
    raw = str(value or "[]")
    return [] if raw == "[]" else json.loads(raw)


def _read_plan_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata, _ = parse(path.read_bytes())
    except OSError, ValueError:
        return {}
    return metadata


def _is_decision_file(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(value, dict) and value.get("type") in DECISION_FILE_TYPES
    except OSError, UnicodeError, json.JSONDecodeError:
        return False


def _orphan_decisions(working: Path, facts: CollectorFacts | None = None) -> list[Path]:
    plans_dir = working / "plans"
    paths: list[Path] = []
    status.collect_plan_paths(plans_dir, paths, [0])
    plans = []
    files = []
    for plan_path in paths:
        if plan_path.name != "plan.md":
            continue
        record = status.read_plan(plan_path, 60)
        if record is None:
            continue
        bucket = status.status_bucket(record["status"])
        plans.append((plan_path, bucket))
        if bucket == "terminal":
            continue
        for path in plan_path.parent.rglob("*.json"):
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            files.append((plan_path.parent, path, _is_decision_file(path), modified))
    messages = facts.messages if facts is not None else _messages(working)
    message_notes = [
        message["notes"]
        for message in messages
        if isinstance(message.get("notes"), str) and message["notes"]
    ]
    return orphan_decisions(plans, files, message_notes, time.time())


def watch_state_detail(
    state: str,
    detail: str,
    record: dict[str, Any],
    repo: Path,
    tasks: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    working: Path,
    now: float,
    newest_activity: float,
    idle: int,
    facts: CollectorFacts | None = None,
) -> tuple[str, str, bool]:
    awaiting = (
        awaiting_user_from_facts(facts, record) is not None
        if facts is not None
        else awaiting_user(record, working) is not None
    )
    git_facts = facts.git if facts is not None else None
    approved = (
        approved_merge_detail(record, repo, now, git_facts)
        if awaiting or state != "needs-decision"
        else None
    )
    has_handback = (
        (
            owner_message_after(facts.messages, str(record["id"]), newest_activity)
            if facts is not None
            else _has_owner_message_after(working, str(record["id"]), newest_activity)
        )
        if not awaiting and state == "stale"
        else False
    )
    stalled = (
        stalled_detail(
            record,
            tasks,
            bindings,
            working,
            now,
            list(facts.messages) if facts is not None else None,
        )
        if not awaiting and state != "needs-decision" and not approved
        else None
    )
    return view_watch_state_detail(
        WatchTransitionFacts(
            state,
            detail,
            idle,
            awaiting,
            approved,
            has_handback,
            stalled,
        )
    )


def approved_merge_detail(
    record: dict[str, Any], repo: Path, now: float, facts: GitFacts | None = None
) -> str | None:
    approved = record.get("merge_approved_at")
    elapsed = approved_merge_elapsed(approved, now)
    if elapsed is None:
        return None
    identifier = str(record["id"])
    branch = record.get("branch") or f"worktree/{identifier}"
    if not isinstance(branch, str) or not branch:
        return None
    exists = (
        branch in facts.branches if facts is not None else branch_exists(repo, branch)
    )
    merged = (
        (branch in facts.merged)
        if facts is not None and exists
        else is_merged(repo, branch)
        if exists
        else False
    )
    return view_approved_merge_detail(elapsed, exists, merged)


def _plan_runtime_metadata(
    path: Path | str,
    record: dict[str, Any],
    tasks: list[dict[str, str]],
    all_ids: set[str],
    branches: dict[str, float],
    worktrees: dict[str, Path],
    bound_branches: list[str] | None = None,
) -> dict[str, Any]:
    metadata = record.get("_metadata") or _read_plan_metadata(Path(path))
    bound_branches = bound_branches or _bound_branches(record, tasks, all_ids, branches)
    worktree = next(
        (str(worktrees[name]) for name in bound_branches if name in worktrees),
        metadata.get("worktree"),
    )
    return {"model": metadata.get("model"), "worktree": worktree}


def _whole_plan_waiting_on_blocked(tasks: list[dict[str, Any]]) -> bool:
    return whole_plan_waiting_on_blocked(tasks)


def _latest_activity(
    working: Path,
    plans_dir: Path,
    plan: Path,
    record: dict[str, Any],
    tasks: list[dict[str, Any]],
    all_ids: set[str],
    branches: dict[str, float],
    worktrees: dict[str, Path],
    worktree_activity: dict[str, tuple[float, str] | None] | None = None,
    now_timestamp: float | None = None,
) -> tuple[float | None, str]:
    try:
        latest = max(
            item.stat().st_mtime for item in plan.parent.rglob("*") if item.is_file()
        )
    except OSError, ValueError:
        return None, "plan files"
    source = "plan files"
    task_times = []
    for task in tasks:
        status_at = task.get("status_at")
        if not isinstance(status_at, str):
            continue
        task_activity = status.parse_status_at(status_at)
        if task_activity is None:
            continue
        task_times.append(task_activity)
    now_time = (
        now_timestamp
        if worktree_activity is not None
        else status._now_line_timestamp(plans_dir, plan)
    )
    candidates = []
    branch_names = _bound_branches(record, tasks, all_ids, branches)
    for branch in branch_names:
        if branch in branches:
            candidates.append((branches[branch], "commit"))
        worktree = worktrees.get(branch)
        if worktree is not None:
            activity = (
                worktree_activity.get(branch)
                if worktree_activity is not None
                else _worktree_activity(worktree)
            )
            if activity is not None:
                candidates.append(activity)
    return latest_activity(
        ActivityFacts(latest, source, tuple(task_times), now_time, tuple(candidates))
    )


def _latest_index_activity(
    file_activity: float | None,
    record: dict[str, Any],
    tasks: list[dict[str, Any]],
    bound_branches: list[str],
    branches: dict[str, float],
    worktrees: dict[str, Path],
    worktree_activity: dict[str, tuple[float, str] | None],
    now_timestamp: float | None,
) -> tuple[float | None, str]:
    if file_activity is None:
        return None, "plan files"
    task_times = [
        parsed
        for task in tasks
        if isinstance(task.get("status_at"), str)
        if (parsed := status.parse_status_at(task["status_at"])) is not None
    ]
    candidates = []
    for branch in bound_branches:
        if branch in branches:
            candidates.append((branches[branch], "commit"))
        activity = worktree_activity.get(branch)
        if branch in worktrees and activity is not None:
            candidates.append(activity)
    return latest_activity(
        ActivityFacts(
            file_activity,
            "plan files",
            tuple(task_times),
            now_timestamp,
            tuple(candidates),
        )
    )


def _iso_timestamp(timestamp: float | None) -> str | None:
    return (
        datetime.fromtimestamp(timestamp, UTC).isoformat()
        if timestamp is not None
        else None
    )


def _read_branches(repo: Path) -> dict[str, float]:
    result = git(
        repo,
        [
            "for-each-ref",
            "refs/heads",
            "--format=%(refname:short)\t%(committerdate:unix)",
        ],
    )
    if result is None or result[0] != 0:
        return {}
    branches = {}
    for line in result[1].splitlines():
        name, separator, raw_time = line.partition("\t")
        if not separator:
            continue
        try:
            branches[name] = float(int(raw_time))
        except ValueError:
            continue
    return branches


def _read_worktrees(repo: Path) -> dict[str, Path]:
    result = git(repo, ["worktree", "list", "--porcelain"])
    if result is None or result[0] != 0:
        return {}
    worktrees = {}
    path = None
    branch = None
    for line in result[1].splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = Path(line.removeprefix("worktree ")), None
        elif line.startswith("branch refs/heads/"):
            branch = line.removeprefix("branch refs/heads/")
        elif not line and path is not None and branch is not None:
            worktrees[branch] = path
            path, branch = None, None
    return worktrees


def _bound_branches(record, tasks, all_ids, branches):
    return view_bound_branches(record, tasks, all_ids, branches)


def _worktree_activity(worktree: Path) -> tuple[float, str] | None:
    latest = None
    result = git(worktree, ["status", "--porcelain"])
    if result is not None and result[0] == 0:
        for line in result[1].splitlines():
            if len(line) < 4:
                continue
            relative = line[3:].rsplit(" -> ", 1)[-1].strip().strip('"')
            try:
                modified = (worktree / relative).stat().st_mtime
            except OSError:
                continue
            if latest is None or modified >= latest[0]:
                latest = (modified, "uncommitted change")
    for relative in (
        "clis/target/debug/deps",
        "clis/target/debug/.fingerprint",
        "clis/target/debug/build",
    ):
        try:
            modified = (worktree / relative).stat().st_mtime
        except OSError:
            continue
        if latest is None or modified >= latest[0]:
            latest = (modified, "build output")
    return latest


def _waiting_is_live(
    working: Path, plans_dir: Path, plan: Path, now: float, threshold: int
) -> bool:
    from varde_workflow.commands.now import line_paths

    modified_times = []
    for path in line_paths(plans_dir, plan):
        try:
            modified_times.append(path.stat().st_mtime)
        except OSError:
            continue
    return waiting_is_live(now, modified_times, threshold)


def _has_owner_message_after(working: Path, plan_id: str, activity: float) -> bool:
    return owner_message_after(_messages(working), plan_id, activity)


def _messages(working: Path) -> list[dict[str, Any]]:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    return [
        {
            "id": message.id,
            "ts": message.ts,
            "from": message.from_,
            "to": message.to,
            "kind": message.kind,
            "text": message.text,
            "notes": message.notes,
        }
        for message in open_data(working, load_data_config())
        .messages.read_all()
        .records
    ]


def run_frames(
    fixtures: Iterable[Iterable[dict[str, Any]]],
    *,
    limit: int,
    clock: Callable[[], float],
    json_output: bool = False,
    threshold: int = 60,
) -> list[str]:
    """Render a bounded set of frames, useful for bounded frame tests."""
    output = []
    for _, events in fixture_frames(
        fixtures, limit=limit, clock=clock, threshold=threshold
    ):
        output.extend(
            json.dumps(event.to_json(), separators=(",", ":"))
            if json_output
            else event.line()
            for event in events
        )
    return output


def run_watch(
    args: Any,
    *,
    frame_limit: int | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Run watch with injectable time and an optional deterministic frame cap."""
    working = Path(
        getattr(args, "working", MemoryPaths.resolve(Path.cwd()).working.path)
    )
    repo = Path(getattr(args, "repo", None) or Path.cwd())
    repo_handle = open_fresh_plans(working)
    git_facts = get_git_facts(repo, refresh=True)
    facts = gather_collector_facts(working, git_facts)
    interval, stale = _watch_timing(args)
    limit = 1 if getattr(args, "once", False) else frame_limit
    use_cache = not (getattr(args, "once", False) and getattr(args, "no_inbox", False))
    notes_value = getattr(args, "notes", None)
    notes = Path(notes_value) if notes_value else None
    stored_cache = read_for_repo(working, notes, repo) if use_cache else None
    seed = use_cache and stored_cache is None
    cache = stored_cache or WatchCache()
    wake = None
    last_orphan_scan: float | None = None
    if not getattr(args, "no_wake", False):
        from varde_workflow.commands.wake import WakeRunner

        wake = WakeRunner.load()
    frame = 0
    while limit is None or frame < limit:
        facts = _refresh_watch_facts(repo_handle, working, repo)
        timestamp = clock()
        plans = collect_watch(
            repo_handle,
            facts,
            now=timestamp,
            threshold_secs=stale,
            working=working,
            repo=repo,
        )
        events, cache = frame_events(plans, timestamp, stale, cache, seed=seed)
        seed = False
        if notes is not None:
            from varde_workflow.commands.watch_block import write_block
            from varde_workflow.commands.watch_state import model

            write_block(notes, model(plans))
        orphan_check_at = monotonic()
        if not getattr(args, "no_inbox", False) and (
            last_orphan_scan is None or orphan_check_at - last_orphan_scan >= 60
        ):
            from varde_workflow.commands.msg import append_event_message

            for decision in _orphan_decisions(working, facts):
                append_event_message(
                    working,
                    "varde-watch",
                    "main",
                    "needs-user",
                    f"Unreferenced decision file: {decision}",
                    notes=decision,
                )
            last_orphan_scan = orphan_check_at
        snapshot_json = _snapshot_json(args)
        for event in events:
            if not snapshot_json:
                print(
                    json.dumps(event.to_json(), separators=(",", ":"))
                    if getattr(args, "json", False)
                    else event.line()
                )
            if not getattr(args, "no_inbox", False):
                from varde_workflow.commands.msg import append_event_message

                kind = {"needs-decision": "needs-user", "finished": "done"}.get(
                    event.kind, event.kind
                )
                append_event_message(working, "varde-watch", "main", kind, event.line())
            if wake is not None:
                wake.run(event)
        if snapshot_json:
            snapshot = events[0].to_json() if events else {"kind": "snapshot"}
            print(
                json.dumps(
                    {
                        **snapshot,
                        "plans": plans,
                        "events": [event.to_json() for event in events],
                    },
                    separators=(",", ":"),
                )
            )
        frame += 1
        if use_cache:
            write_if_changed_for_repo(working, notes, repo, cache)
        if limit is None or frame < limit:
            sleep(interval)
    return 0


def _refresh_watch_facts(repo_handle: Any, working: Path, repo: Path) -> CollectorFacts:
    repo_handle.refresh()
    return gather_collector_facts(working, get_git_facts(repo))


def _snapshot_json(args: Any) -> bool:
    return bool(
        getattr(args, "once", False)
        and getattr(args, "no_inbox", False)
        and getattr(args, "json", False)
    )


def _watch_timing(args: Any) -> tuple[int, int]:
    interval = max(0, int(getattr(args, "interval", 60)))
    stale_value = getattr(args, "stale", None)
    stale = 1200 if stale_value is None else int(stale_value)
    return interval, stale
