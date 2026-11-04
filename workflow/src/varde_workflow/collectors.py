"""Library collectors shared by the CLI and the runner."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.views import (
    awaiting_user_message,
    classify_status,
    count_open_questions,
    merge_verdict,
    parse_status_at,
    path_sort_key,
    plan_progress,
    stalled_minutes,
)
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
    frame_events as _frame_events,
)
from varde_data.views.watch import (
    watch_state_detail as view_watch_state_detail,
)
from varde_learn.knowledge.frontmatter import parse

from varde_workflow.merge_state import (
    awaiting_user,
    branch_exists,
    is_merged,
    json_merge_state,
    stalled_detail,
)
from varde_workflow.plan_labels import resolve_group, resolve_parent_group
from varde_workflow.schema import TASK_ACTIVE
from varde_workflow.watch_cache import WatchCache

TASK_ACTIVE_STATES = set(TASK_ACTIVE)
status_bucket = classify_status
view_count_open_questions = count_open_questions


def parse_stale_seconds(value: str) -> int:
    factors = {"s": 1, "m": 60, "h": 3600}
    if (
        len(value) < 2
        or value[-1] not in factors
        or not value[:-1].isdigit()
        or int(value[:-1]) <= 0
    ):
        raise ValueError(f"invalid stale duration: {value}")
    return int(value[:-1]) * factors[value[-1]]


@dataclass(frozen=True)
class GitFacts:
    refs_signature: tuple[tuple[str, int, int, int], ...]
    branches: dict[str, float]
    merged: frozenset[str]
    worktrees: dict[str, Path]
    worktree_activity: dict[str, tuple[float, str] | None]


@dataclass(frozen=True)
class CollectorFacts:
    git: GitFacts
    messages: tuple[dict[str, Any], ...]
    bindings: tuple[dict[str, Any], ...]
    decision_titles: dict[str, str]
    source_version: tuple[str, str]
    decision_signature: tuple[tuple[str, int, int, int], ...]


@dataclass(frozen=True)
class StatusContext:
    notes: dict[str, object]
    reviews: dict[str, object]
    now_lines: dict[str, dict[str, object]]
    git: GitFacts
    repo: Path
    working: Path
    timestamp: float
    stall_minutes: int
    facts: CollectorFacts


_facts_cache: dict[Path, CollectorFacts] = {}


def gather_collector_facts(working: Path, git: GitFacts) -> CollectorFacts:
    """Read message and binding stores once per repository version."""
    working = working.resolve()
    data = open_data(working, load_data_config())
    version = (str(data.messages.version().value), str(data.addresses.version().value))
    cached = _facts_cache.get(working)
    if cached is not None and cached.source_version == version:
        signature = _decision_signature(cached.messages)
        if signature == cached.decision_signature:
            return CollectorFacts(
                git,
                cached.messages,
                cached.bindings,
                cached.decision_titles,
                version,
                signature,
            )
    messages = tuple(_message_row(row) for row in data.messages.read_all().records)
    bindings = tuple(_binding_row(row) for row in data.addresses.list_bindings())
    titles = _decision_titles(messages)
    facts = CollectorFacts(
        git, messages, bindings, titles, version, _decision_signature(messages)
    )
    _facts_cache[working] = facts
    return facts


def _message_row(message: Any) -> dict[str, Any]:
    return {
        "id": message.id,
        "ts": message.ts,
        "from": message.from_,
        "to": message.to,
        "kind": message.kind,
        "text": message.text,
        "notes": message.notes,
    }


def _binding_row(binding: Any) -> dict[str, Any]:
    return {
        "address": binding.address,
        "session_id": binding.session_id,
        "harness": binding.harness,
        "bound_at": binding.bound_at.isoformat(),
        "last_seen": binding.last_seen.isoformat(),
        "token_id": binding.token_id,
        **binding.extra,
    }


def _decision_titles(messages: tuple[dict[str, Any], ...]) -> dict[str, str]:
    titles = {}
    for message in messages:
        note = message.get("notes")
        if not isinstance(note, str) or note in titles:
            continue
        title = _decision_title(Path(note))
        if title is not None:
            titles[note] = title
    return titles


def _decision_signature(
    messages: tuple[dict[str, Any], ...],
) -> tuple[tuple[str, int, int, int], ...]:
    signature = []
    for message in messages:
        note = message.get("notes")
        if not isinstance(note, str):
            continue
        try:
            info = Path(note).stat()
            signature.append((note, info.st_mtime_ns, info.st_size, info.st_ino))
        except OSError:
            signature.append((note, 0, 0, 0))
    return tuple(sorted(set(signature)))


def _decision_title(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return None
    title = value.get("title") if isinstance(value, dict) else None
    return title if isinstance(title, str) and title else None


def awaiting_user_from_facts(
    facts: CollectorFacts, record: dict[str, Any]
) -> str | None:
    if (
        not record.get("assigned_to")
        or classify_status(str(record.get("status", ""))) == "terminal"
    ):
        return None
    pending = awaiting_user_message(record, facts.messages)
    if pending is None:
        return None
    note = pending.get("notes")
    title = facts.decision_titles.get(note) if isinstance(note, str) else None
    if title:
        return title
    text = pending.get("text")
    return (
        text.strip()
        if isinstance(text, str) and text.strip()
        else "Waiting on your decision"
    )


def collect_status(
    repo_handle: Any,
    facts: CollectorFacts,
    *,
    now: float | None = None,
    stall_minutes: int = 60,
    working: Path | None = None,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Collect status from index rows and already-computed external facts."""
    working = Path(working or repo_handle.working)
    plans_dir = working / "plans"
    timestamp = time.time() if now is None else now
    indexed = repo_handle.status_rows()
    plans = [row for row in indexed["plans"] if not row.get("archived")]
    task_rows = [row for row in indexed["tasks"] if not row.get("archived")]
    plans.extend(
        {
            **row,
            "artifact_type": "standalone-task",
            "id": str(row["path"]).rsplit("/", 2)[-2],
            "status": row.get("status") or "todo",
            "title": row.get("title") or str(row["path"]).rsplit("/", 2)[-2],
            "label": row.get("title"),
            "depends_on_json": row.get("depends_on_json", "[]"),
        }
        for row in task_rows
        if str(row["path"]).endswith("/task.md")
    )
    reviews = {str(row["plan_path"]): row.get("verdict") for row in indexed["reviews"]}
    notes = {
        str(row["task_path"]): row.get("mtime_ns") for row in indexed["task_notes"]
    }
    now_lines = {str(row["plan_key"]): row for row in indexed["now_lines"]}
    tasks_by_plan: dict[str, list[dict[str, Any]]] = {}
    for row in task_rows:
        tasks_by_plan.setdefault(str(row["plan_path"]), []).append(row)
    context = StatusContext(
        notes,
        reviews,
        now_lines,
        facts.git,
        Path(repo or Path.cwd()),
        working,
        timestamp,
        stall_minutes,
        facts,
    )
    records: dict[str, dict[str, Any]] = {}
    parent_groups: dict[str, str] = {}
    plans_dir_text = str(plans_dir)
    indexed_paths = {str(row["path"]) for row in plans}
    ordered = sorted(
        plans,
        key=lambda row: (
            str(row["path"]).count("/"),
            path_sort_key(str(row["path"]).rsplit("/", 2)[-2]),
        ),
    )
    for row in ordered:
        path = str(row["path"])
        kind = str(row["artifact_type"])
        if kind == "task":
            continue
        inherited = _inherited_group(path, plans_dir_text, indexed_paths, parent_groups)
        record = _indexed_status_record(
            row,
            inherited,
            tasks_by_plan.get(str(path), []),
            context,
        )
        if record is None:
            continue
        records[path] = record
        parent_groups[path] = str(record["group_name"])
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    record_paths = set(records)
    for path in record_paths:
        parent = _parent_plan_text(path, plans_dir_text, record_paths)
        if parent:
            children.setdefault(parent, []).append(path)
        else:
            roots.append(path)
    by_key = records
    view_children = children
    skipped = sum(
        not row.get("archived")
        and (
            row.get("kind") == "document"
            or (
                row.get("kind") == "task"
                and str(row["path"]).rsplit("/", 1)[-1] in {"plan.md", "task.md"}
            )
        )
        for row in indexed["invalid"]
    ) + sum(int(row.get("skipped_tasks") or 0) for row in plans)
    return {
        **plan_progress(by_key, view_children, roots),
        "skipped": skipped,
    }


def _index_now_key(plans_dir: str, path: str) -> str:
    relative = path.removeprefix(plans_dir + "/").rsplit("/", 1)[0]
    return "__".join(part.replace("_", "_u") for part in relative.split("/"))


def _inherited_group(
    path: str,
    plans_dir: str,
    discovered: set[str],
    parent_groups: dict[str, str],
) -> str:
    parent = _parent_plan_text(path, plans_dir, discovered)
    ancestors = []
    while parent is not None:
        ancestors.append(parent_groups.get(parent))
        parent = _parent_plan_text(parent, plans_dir, discovered)
    return resolve_parent_group(ancestors)


def _indexed_status_record(
    row: dict[str, object],
    inherited: str,
    task_rows: list[dict[str, object]],
    context: StatusContext,
) -> dict[str, Any] | None:
    path = str(row["path"])
    identifier = str(row["id"])
    status_value = str(row.get("status") or "backlog")
    if row.get("artifact_type") == "standalone-task":
        fields = {"depends_on": _dependency_list(row.get("depends_on_json"))}
        return _standalone_task_record(
            row, fields, path, identifier, status_value, context
        )
    return _indexed_plan_record(row, inherited, task_rows, context)


def _indexed_plan_record(
    row: dict[str, object],
    inherited: str,
    task_rows: list[dict[str, object]],
    context: StatusContext,
) -> dict[str, Any] | None:
    path = str(row["path"])
    try:
        group_value = json.loads(str(row["group_json"]))
    except TypeError, ValueError:
        return None
    fields = {
        "group": group_value,
        "shape": row.get("shape"),
        "depends_on": _dependency_list(row.get("depends_on_json")),
    }
    tasks = [_indexed_task(task) for task in task_rows]
    record = _plan_status_record(row, fields, inherited, tasks, context)
    facts = context.git
    repo = context.repo
    record["merge_state"] = json_merge_state(
        record, repo, frozenset(facts.branches), facts.merged
    )
    working = context.working
    record["awaiting_user"] = awaiting_user_from_facts(context.facts, record)
    if record.get("assigned_to"):
        record["stalled"] = (
            stalled_detail(
                record,
                tasks,
                list(context.facts.bindings),
                working,
                context.timestamp,
                list(context.facts.messages),
            )
            is not None
        )
    line = context.now_lines.get(_index_now_key(str(working / "plans"), path), {})
    record["now"] = line.get("text")
    mtime = line.get("mtime_ns")
    record["now_at"] = (
        datetime.fromtimestamp(int(cast("int", mtime)) / 1e9).astimezone().isoformat()
        if mtime
        else None
    )
    return record


def _standalone_task_record(
    row: dict[str, object],
    fields: dict[str, Any],
    path: str,
    identifier: str,
    status_value: str,
    context: StatusContext,
) -> dict[str, Any]:
    title = row.get("title") or identifier
    line = context.now_lines.get(
        _index_now_key(str(context.working / "plans"), path), {}
    )
    modified = line.get("mtime_ns")
    return {
        "id": identifier,
        "status": status_value,
        "title": title,
        "label": str(row.get("label") or title).strip(),
        "group_name": "",
        "owner": None,
        "group": False,
        "questions": 0,
        "done": 0,
        "total": 0,
        "in_progress": False,
        "status_at": row.get("status_at"),
        "task_now": None,
        "depends": _dependency_list(row.get("depends_on_json")),
        "terminal": status_bucket(status_value) == "terminal",
        "merge": "none",
        "merge_state": "absent",
        "stalled": False,
        "now": line.get("text"),
        "now_at": (
            datetime.fromtimestamp(int(cast("int", modified)) / 1e9)
            .astimezone()
            .isoformat()
            if modified
            else None
        ),
        "path": str(path),
    }


def _plan_status_record(
    row: dict[str, object],
    fields: dict[str, Any],
    inherited: str,
    tasks: list[dict[str, Any]],
    context: StatusContext,
) -> dict[str, Any]:
    path = str(row["path"])
    status_value = str(row.get("status") or "backlog")
    identifier = str(row["id"])
    title = row.get("title") or identifier
    label = str(row.get("label") or title).strip() or title
    review = context.reviews.get(path)
    return {
        "id": identifier,
        "status": status_value,
        "title": title,
        "label": label,
        "purpose": row.get("purpose") or "",
        "group_name": resolve_group(fields.get("group"), inherited),
        "owner": row.get("owner"),
        "assigned_to": row.get("assigned_to"),
        "merge_approved_at": row.get("merge_approved_at"),
        "merge_state": "none",
        "stalled": False,
        "branch": row.get("branch"),
        "group": fields.get("shape") == "group",
        "questions": view_count_open_questions(
            "## Open questions\n" + str(row.get("open_questions") or "")
        ),
        **_indexed_task_progress(
            tasks, context.notes, context.timestamp, context.stall_minutes
        ),
        "depends": fields.get("depends_on", []),
        "terminal": status_bucket(status_value) == "terminal",
        "merge": merge_verdict(
            review if isinstance(review, str) else None, status_value
        ),
        "path": path,
        "awaiting_user": None,
        "now": None,
        "now_at": None,
    }


def _indexed_task(row: dict[str, object]) -> dict[str, Any]:
    path = str(row["path"])
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    return {
        "id": str(row["id"]),
        "stem": stem,
        "status": str(row.get("status") or "todo"),
        "status_at": row.get("status_at"),
        "depends": _dependency_list(row.get("depends_on_json")),
        "title": row.get("title") if isinstance(row.get("title"), str) else stem,
        "path": path,
        "mtime_ns": row.get("mtime_ns"),
    }


def _indexed_task_progress(
    tasks: list[dict[str, Any]], notes: dict[str, object], now: float, stall: int
) -> dict[str, Any]:
    done = sum(status_bucket(task["status"]) == "terminal" for task in tasks)
    active = next((task for task in tasks if task["status"] in TASK_ACTIVE), None)
    terminal = {
        identifier
        for task in tasks
        if status_bucket(task["status"]) == "terminal"
        for identifier in (task["id"], task["stem"])
    }
    ready = next(
        (
            task
            for task in tasks
            if status_bucket(task["status"]) != "terminal"
            and task["status"] not in TASK_ACTIVE
            and all(
                not isinstance(dependency, str) or dependency in terminal
                for dependency in task["depends"]
            )
        ),
        None,
    )
    current = (
        f"{active['title']} {active['status'].replace('_', ' ')}"
        if active
        else f"next: {ready['title']}"
        if ready
        else None
    )
    if active:
        activity = float(active["mtime_ns"] or 0) / 1e9
        value = active["status_at"]
        if isinstance(value, str) and (parsed := parse_status_at(value)) is not None:
            activity = parsed
        plan_dir = active["path"].rsplit("/", 2)[0]
        note_time = notes.get(f"{plan_dir}/notes/{active['id']}.md")
        if isinstance(note_time, int):
            activity = max(activity, note_time / 1e9)
        elapsed = stalled_minutes(now, activity, stall)
        if elapsed is not None and current:
            current = current.replace(
                f" {active['status'].replace('_', ' ')}", f" stalled {elapsed}m"
            )
    return {
        "done": done,
        "total": len(tasks),
        "in_progress": active is not None,
        "task_now": current,
    }


def _dependency_list(value: object) -> list[str]:
    raw = str(value or "[]")
    if raw == "[]":
        return []
    try:
        parsed = json.loads(raw)
    except TypeError, ValueError:
        return []
    values = parsed if isinstance(parsed, list) else [parsed]
    return [item for item in values if isinstance(item, str)]


def _parent_plan_text(path: str, plans_dir: str, paths: set[str]) -> str | None:
    directory = path.rsplit("/", 1)[0]
    while directory == plans_dir or directory.startswith(plans_dir + "/"):
        candidate = f"{directory}/plan.md"
        if candidate != path and candidate in paths:
            return candidate
        if directory == plans_dir:
            break
        directory = directory.rsplit("/", 1)[0]
    return None


def frame_events(
    snapshot: Iterable[dict[str, Any]],
    now: float,
    threshold: int,
    previous: WatchCache | None = None,
    *,
    seed: bool = False,
) -> tuple[list[Event], WatchCache]:
    """Classify one snapshot and return its events and next cache."""
    old = (previous or WatchCache()).plans
    events, states = _frame_events(
        snapshot,
        now,
        threshold,
        old,
        seed=seed,
    )
    return events, WatchCache(plans=cast("Any", states))


def collect_watch(
    repo_handle: Any,
    facts: CollectorFacts,
    *,
    now: float,
    threshold_secs: int = 1200,
    working: Path | None = None,
    repo: Path | None = None,
) -> list[dict[str, Any]]:
    """Build a watch snapshot from lightweight index rows and cached Git facts."""
    working = Path(working or repo_handle.working)
    repo = Path(repo or Path.cwd())
    plans_dir = working / "plans"
    indexed = repo_handle.watch_rows()
    plan_rows = indexed["plans"]
    task_rows = indexed["tasks"]
    now_rows = {str(row["plan_key"]): row for row in indexed["now_lines"]}
    activity_rows = {str(row["plan_path"]): row for row in indexed["activity"]}
    tasks_by_plan: dict[str, list[dict[str, Any]]] = {}
    for row in task_rows:
        depends = _decode_dependencies(row.get("depends_on_json"))
        task_path = str(row["path"])
        stem = task_path.rsplit("/", 1)[-1].removesuffix(".md")
        tasks_by_plan.setdefault(str(row["plan_path"]), []).append(
            {
                "id": str(row["id"]),
                "stem": stem,
                "status": str(row.get("status") or "todo"),
                "status_at": row.get("status_at"),
                "depends": depends
                if isinstance(depends, list)
                else [depends]
                if isinstance(depends, str)
                else [],
                "title": row.get("title")
                if isinstance(row.get("title"), str)
                else stem,
                "path": task_path,
            }
        )
    rows = sorted(
        (row for row in plan_rows if row.get("artifact_type") == "plan"),
        key=lambda row: str(row["id"]),
    )
    all_ids = {str(row["id"]) for row in rows}
    branch_owners = _branch_owners(all_ids, facts.git.branches)
    bindings = list(facts.bindings)
    output = []
    for row in rows:
        artifact_status = str(row.get("status") or "backlog")
        bucket = classify_status(artifact_status)
        if bucket == "backlog":
            continue
        path = str(row["path"])
        metadata = {"model": row.get("model"), "worktree": row.get("worktree")}
        record = {
            "id": str(row["id"]),
            "path": path,
            "status": artifact_status,
            "owner": row.get("owner"),
            "assigned_to": row.get("assigned_to"),
            "merge_approved_at": row.get("merge_approved_at"),
            "branch": row.get("branch"),
            "questions": count_open_questions(
                "## Open questions\n" + str(row.get("open_questions") or "")
            ),
            "_metadata": metadata,
        }
        tasks = tasks_by_plan.get(str(path), [])
        now_key = _watch_now_key(str(plans_dir), path)
        bound_branches = _indexed_bound_branches(record, tasks, branch_owners)
        activity_row = activity_rows.get(path)
        newest, source = _latest_index_activity(
            float(activity_row["newest_mtime_ns"]) / 1e9
            if activity_row is not None
            else None,
            record,
            tasks,
            bound_branches,
            facts.git.branches,
            facts.git.worktrees,
            facts.git.worktree_activity,
            int(now_rows[now_key]["mtime_ns"]) / 1e9
            if now_rows.get(now_key, {}).get("mtime_ns")
            else None,
        )
        if newest is None:
            continue
        now_row = now_rows.get(now_key, {})
        now_line = now_row.get("text")
        done, total, blocked = task_counts(tasks)
        plan_age = (
            max(0, int(now - int(row["mtime_ns"]) / 1e9))
            if bucket == "terminal"
            else None
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
                questions=record["questions"],
                plan_age=plan_age,
                now_line=now_line,
                waiting_live=bool(
                    is_waiting_line(now_line)
                    and waiting_is_live(
                        now,
                        [int(now_row["mtime_ns"]) / 1e9]
                        if now_row.get("mtime_ns")
                        else [],
                        threshold_secs,
                    )
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
            facts,
        )
        json_state = _plan_json_state(
            record, repo, tasks, bindings, working, now, facts.git, facts
        )
        output.append(
            {
                "id": str(row["id"]),
                "owner": row.get("owner"),
                "assigned_to": row.get("assigned_to"),
                "merge_approved_at": row.get("merge_approved_at"),
                **json_state,
                "status": artifact_status,
                "state": state,
                "detail": detail,
                **_plan_runtime_metadata(
                    path,
                    record,
                    tasks,
                    all_ids,
                    facts.git.branches,
                    facts.git.worktrees,
                    bound_branches,
                ),
                "last_event_at": datetime.fromtimestamp(newest, UTC).isoformat(),
                "done": done,
                "total": total,
                "blocked_tasks": blocked,
                "open_questions": record["questions"],
                "now_line": now_line,
                "now_at": _iso_timestamp(
                    int(now_row["mtime_ns"]) / 1e9 if now_row.get("mtime_ns") else None
                ),
                "newest_activity": newest,
                "idle_no_handback": idle_no_handback,
                "bucket": idle_bucket(state, idle, threshold_secs),
            }
        )
    return output


def _watch_now_key(plans_dir: str, path: str) -> str:
    relative = path.removeprefix(plans_dir + "/").rsplit("/", 1)[0]
    return "__".join(component.replace("_", "_u") for component in relative.split("/"))


def _plan_json_state(  # noqa: PLR0913, PLR0917 - classifier data stays explicit.
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
    if raw == "[]":
        return []
    try:
        return json.loads(raw)
    except TypeError, ValueError:
        return []


def watch_state_detail(  # noqa: PLR0913, PLR0917 - classifier data stays explicit.
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


def _plan_runtime_metadata(  # noqa: PLR0913, PLR0917 - classifier data stays explicit.
    path: Path | str,
    record: dict[str, Any],
    tasks: list[dict[str, str]],
    all_ids: set[str],
    branches: dict[str, float],
    worktrees: dict[str, Path],
    bound_branches: list[str] | None = None,
) -> dict[str, Any]:
    metadata = record.get("_metadata") or _read_plan_metadata(Path(path))
    if bound_branches is None:
        bound_branches = _bound_branches(record, tasks, all_ids, branches)
    worktree = next(
        (str(worktrees[name]) for name in bound_branches if name in worktrees),
        metadata.get("worktree"),
    )
    return {"model": metadata.get("model"), "worktree": worktree}


def _whole_plan_waiting_on_blocked(tasks: list[dict[str, Any]]) -> bool:
    return whole_plan_waiting_on_blocked(tasks)


def _latest_index_activity(  # noqa: PLR0913, PLR0917 - classifier data stays explicit.
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
    task_times = []
    for task in tasks:
        status_at = task.get("status_at")
        if not isinstance(status_at, str):
            continue
        parsed = parse_status_at(status_at)
        if parsed is not None:
            task_times.append(parsed)
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


def _has_owner_message_after(working: Path, plan_id: str, activity: float) -> bool:
    messages = open_data(working, load_data_config()).messages.read_all().records
    rows = tuple(_message_row(message) for message in messages)
    return owner_message_after(rows, plan_id, activity)


def _iso_timestamp(timestamp: float | None) -> str | None:
    return (
        datetime.fromtimestamp(timestamp, UTC).isoformat()
        if timestamp is not None
        else None
    )


def _read_plan_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata, _ = parse(path.read_bytes())
    except OSError, ValueError:
        return {}
    return metadata


def _bound_branches(record, tasks, all_ids, branches):
    plan_id = str(record["id"])
    exact = {f"worktree/{plan_id}", *(f"worktree/{task['id']}" for task in tasks)}
    branch = record.get("branch")
    if isinstance(branch, str) and branch:
        exact.add(branch)
    return sorted(
        name
        for name in branches
        if name in exact
        or (
            name.startswith(f"worktree/{plan_id}-")
            and not any(
                name.startswith(f"worktree/{other}-")
                for other in all_ids
                if other != plan_id and other.startswith(f"{plan_id}-")
            )
        )
    )
