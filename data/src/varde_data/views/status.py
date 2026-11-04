"""Pure status classification and progress calculations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePath
from types import MappingProxyType
from typing import Literal

from varde_data.records.plans import PlanRecord, TaskRecord

StatusBucket = Literal["terminal", "backlog", "other"]
TERMINAL = frozenset(
    {"cancelled", "done", "complete", "completed", "dismissed", "stale", "archived"}
)
BACKLOG = frozenset({"backlog", "draft", "proposed", "ready"})
TASK_ACTIVE = frozenset(
    {"in_progress", "building", "in_review", "fixing", "integrating"}
)
DISPLAY_LIMIT = 5

__all__ = [
    "BACKLOG",
    "DISPLAY_LIMIT",
    "TASK_ACTIVE",
    "TERMINAL",
    "Binding",
    "StatusBucket",
    "StatusFacts",
    "awaiting_user_message",
    "classify_status",
    "count_open_questions",
    "dependency_order",
    "json_merge_state",
    "merge_verdict",
    "now_line",
    "parse_status_at",
    "path_sort_key",
    "plan_progress",
    "section_bullets",
    "section_span",
    "stalled_detail",
    "stalled_minutes",
    "task_progress",
]


@dataclass(frozen=True)
class Binding:
    """Plain address binding facts needed by plan views."""

    address: str
    plan_id: str | None = None
    branch: str | None = None
    last_seen: str | None = None


@dataclass(frozen=True)
class StatusFacts:
    """External status inputs, collected by an adapter once per run."""

    clock: float
    stall_minutes: int = 60
    now_lines: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    now_line_timestamps: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )
    merged: frozenset[str] = frozenset()
    branches: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    task_activity: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )
    bindings: tuple[Binding, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "now_lines",
            "now_line_timestamps",
            "branches",
            "task_activity",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def __hash__(self) -> int:
        return hash(
            (
                self.clock,
                self.stall_minutes,
                frozenset(self.now_lines.items()),
                frozenset(self.now_line_timestamps.items()),
                self.merged,
                frozenset(self.branches.items()),
                frozenset(self.task_activity.items()),
                self.bindings,
            )
        )


def classify_status(status: str) -> StatusBucket:
    if status in TERMINAL:
        return "terminal"
    if status in BACKLOG:
        return "backlog"
    return "other"


def parse_status_at(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def stalled_minutes(now: float, last_activity: float, threshold: int) -> int | None:
    elapsed = max(0, int((now - last_activity) // 60))
    return elapsed if elapsed >= threshold else None


def task_progress(
    plan: PlanRecord, facts: StatusFacts
) -> dict[str, int | bool | str | None]:
    """Return done/total/current task summary using only stored records and facts."""
    tasks = plan.tasks
    done = sum(classify_status(_task_status(task)) == "terminal" for task in tasks)
    active = next((task for task in tasks if _task_status(task) in TASK_ACTIVE), None)
    ready = next(
        (task for task in tasks if _task_ready(task, tasks)),
        None,
    )
    next_task = ready or next(
        (
            task
            for task in tasks
            if classify_status(_task_status(task)) != "terminal"
            and _task_status(task) not in TASK_ACTIVE
        ),
        None,
    )
    current = (
        f"{_task_title(active)} {_task_state_label(_task_status(active))}"
        if active
        else f"next: {_task_title(next_task)}"
        if next_task
        else None
    )
    if active:
        last_activity = active.mtime
        status_at = active.fields.get("status_at")
        if isinstance(status_at, str):
            parsed = parse_status_at(status_at)
            if parsed is not None:
                last_activity = parsed
        last_activity = max(last_activity, facts.task_activity.get(active.id, 0))
        elapsed = stalled_minutes(facts.clock, last_activity, facts.stall_minutes)
        if elapsed is not None and current is not None:
            current = current.replace(
                f" {_task_state_label(_task_status(active))}",
                f" stalled {elapsed}m",
            )
    return {
        "done": done,
        "total": len(tasks),
        "in_progress": active is not None,
        "now": current,
    }


def _record_now(record: Mapping[str, object]) -> str:
    questions = record.get("questions", 0)
    questions = questions if isinstance(questions, int) else 0
    total = record.get("total", 0)
    total = total if isinstance(total, int) else 0
    done = record.get("done", 0)
    done = done if isinstance(done, int) else 0
    identifier = record.get("id", "")
    is_group = bool(record.get("group"))
    if total == 0 and not is_group and (_is_draft(str(identifier)) or questions):
        noun = "question" if questions == 1 else "questions"
        return f"draft, {questions} open {noun}"
    if record.get("status") == "blocked":
        return "blocked"
    task_now = record.get("task_now")
    if task_now:
        return str(task_now)
    if not is_group and total and done == total:
        return "tasks complete"
    if not is_group and total == 0:
        return "no tasks yet"
    return str(record.get("status", ""))


def _is_draft(identifier: str) -> bool:
    return identifier.endswith("-draft") or bool(
        re.search(r"-draft-[0-9]+$", identifier)
    )


def _has_activity(
    identifier: str,
    records: Mapping[str, Mapping[str, object]],
    children: Mapping[str, tuple[str, ...] | list[str]],
    in_progress: bool,
) -> bool:
    record = records[identifier]
    active = (
        bool(record.get("in_progress")) if in_progress else bool(record.get("total"))
    )
    return active or any(
        _has_activity(child, records, children, in_progress)
        for child in children.get(identifier, ())
    )


def _root_priority(
    identifier: str,
    records: Mapping[str, Mapping[str, object]],
    children: Mapping[str, tuple[str, ...] | list[str]],
) -> int:
    if _has_activity(identifier, records, children, True):
        return 0
    if _has_activity(identifier, records, children, False):
        return 1
    return 2


def _collapsible(
    identifier: str,
    records: Mapping[str, Mapping[str, object]],
    children: Mapping[str, tuple[str, ...] | list[str]],
) -> bool:
    record = records[identifier]
    return (
        record.get("status") == "backlog"
        and not _has_activity(identifier, records, children, False)
        and not _is_draft(str(record.get("id", "")))
        and not record.get("questions")
    )


def _build_progress(
    identifier: str,
    records: Mapping[str, Mapping[str, object]],
    children: Mapping[str, tuple[str, ...] | list[str]],
    siblings: tuple[str, ...] | list[str],
    *,
    limit: int = DISPLAY_LIMIT,
) -> dict[str, object]:
    record = records[identifier]
    child_ids = list(children.get(identifier, ()))
    group = bool(record.get("group")) or bool(child_ids)
    if group:
        done = sum(bool(records[child].get("terminal")) for child in child_ids)
        total = len(child_ids)
        unit = "plans"
    else:
        done_value = record.get("done", 0)
        total_value = record.get("total", 0)
        done = done_value if isinstance(done_value, int) else 0
        total = total_value if isinstance(total_value, int) else 0
        unit = "tasks"
    visible = [child for child in child_ids if not records[child].get("terminal")]
    ordered = _dependency_order_records(visible, records)
    dependencies = record.get("depends", ())
    dependencies = dependencies if isinstance(dependencies, (list, tuple)) else ()
    dependency = next(
        (
            str(records[sibling].get("id", sibling))
            for dependency in dependencies
            for sibling in siblings
            if dependency != record.get("id")
            and records[sibling].get("id") == dependency
            and records[sibling].get("status") != "completed"
        ),
        None,
    )
    current = record.get("now") or (
        f"waits on {dependency}" if total == 0 and dependency else _record_now(record)
    )
    result: dict[str, object] = {
        "id": str(record.get("id", identifier)).replace("—", "-"),
        "title": str(record.get("title", "")).replace("—", "-"),
        "label": str(record.get("label", "")).replace("—", "-"),
        "purpose": str(record.get("purpose", "")).replace("—", "-"),
        "group_name": str(record.get("group_name", "")).replace("—", "-"),
        "status": str(record.get("status", "")).replace("—", "-"),
        "merge": record.get("merge"),
        "done": done,
        "total": total,
        "unit": unit,
        "now": str(current).replace("—", "-"),
        "now_at": record.get("now_at"),
    }
    owner = record.get("owner")
    if owner is not None:
        result["owner"] = str(owner).replace("—", "-")
    for key in ("assigned_to", "merge_approved_at"):
        if record.get(key) is not None:
            result[key] = record[key]
    result.update(
        {
            "merge_state": record.get("merge_state"),
            "stalled": bool(record.get("stalled")),
            "awaiting_user": record.get("awaiting_user"),
            "group": group,
            "children": [
                _build_progress(child, records, children, child_ids, limit=limit)
                for child in ordered[:limit]
            ],
            "more_count": max(0, len(ordered) - limit),
        }
    )
    return result


def _dependency_order_records(
    identifiers: list[str], records: Mapping[str, Mapping[str, object]]
) -> list[str]:
    remaining = sorted(
        identifiers,
        key=lambda identifier: (
            str(records[identifier].get("id", identifier)),
            str(records[identifier]["path"]),
        ),
    )
    ordered = []
    while remaining:
        index = next(
            (
                index
                for index, identifier in enumerate(remaining)
                if not any(
                    dependency in {records[sibling].get("id") for sibling in remaining}
                    for dependency in _string_sequence(
                        records[identifier].get("depends")
                    )
                )
            ),
            None,
        )
        if index is None:
            ordered.extend(remaining)
            break
        ordered.append(remaining.pop(index))
    return ordered


def plan_progress(
    records: Mapping[str, Mapping[str, object]],
    children: Mapping[str, tuple[str, ...] | list[str]],
    roots: tuple[str, ...] | list[str],
    *,
    limit: int = DISPLAY_LIMIT,
) -> dict[str, object]:
    """Build rollups with path-derived root ordering and dependency-ordered children.

    Roots sort first by activity priority, then by the workflow's `_path_sort_key`
    using `PurePath(record.path).parent.name` for dated ordering and
    `str(record.path)` to break ties. Child dependency order uses record id then
    full path. Path handling is lexical and performs no filesystem access.
    """
    siblings = list(roots)
    active_roots = [
        identifier for identifier in siblings if not records[identifier].get("terminal")
    ]
    active_roots.sort(key=lambda identifier: _record_sort_key(records[identifier]))
    backlog = [
        identifier
        for identifier in active_roots
        if _collapsible(identifier, records, children)
    ]
    visible = [identifier for identifier in active_roots if identifier not in backlog]
    visible.sort(
        key=lambda identifier: (
            _root_priority(identifier, records, children),
            _record_sort_key(records[identifier]),
        )
    )
    return {
        "plans": [
            _build_progress(identifier, records, children, siblings, limit=limit)
            for identifier in visible[:limit]
        ],
        "more_count": max(0, len(visible) - limit),
        "backlog_count": len(backlog),
    }


def now_line(record_id: str, facts: StatusFacts) -> tuple[str | None, str | None]:
    line = facts.now_lines.get(record_id)
    timestamp = facts.now_line_timestamps.get(record_id)
    now_at = (
        datetime.fromtimestamp(timestamp).astimezone().isoformat()
        if timestamp is not None
        else None
    )
    return line, now_at


def _record_sort_key(record: Mapping[str, object]) -> tuple[tuple[int, str, str], str]:
    path_value = str(record["path"])
    return path_sort_key(PurePath(path_value).parent.name), path_value


def merge_verdict(review_verdict: str | None, status: str) -> str:
    if review_verdict != "approved":
        return "none"
    return "merged" if status == "completed" else "ready"


def count_open_questions(body: str) -> int:
    span = section_span(body, "open questions")
    if span is None:
        return 0
    start, end = span
    return len(section_bullets(body.splitlines(), start, end))


def section_bullets(
    lines: list[str], start: int, end: int
) -> list[tuple[int, int, str]]:
    bullets = []
    fence: tuple[str, int] | None = None
    index = start
    while index < min(end, len(lines)):
        line = lines[index]
        trimmed = line.lstrip()
        marker = _fence_start(trimmed)
        if fence:
            if _fence_end(trimmed, *fence):
                fence = None
            index += 1
            continue
        if marker:
            fence = marker
            index += 1
            continue
        if line.startswith(("- ", "* ")):
            finish = index + 1
            while finish < min(end, len(lines)):
                continuation = lines[finish]
                if continuation.startswith((" ", "\t")) or not continuation.strip():
                    finish += 1
                    continue
                break
            bullets.append((index, finish, line[2:].strip()))
            index = finish
            continue
        index += 1
    return bullets


def section_span(body: str, title: str) -> tuple[int, int] | None:
    lines = body.splitlines()
    section_level: int | None = None
    section_start: int | None = None
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        trimmed = line.lstrip()
        marker = _fence_start(trimmed)
        if fence:
            if _fence_end(trimmed, *fence):
                fence = None
            continue
        if marker:
            fence = marker
            continue
        heading = re.match(r"^(#{1,6})[ \t]+(.*)$", trimmed)
        if heading:
            level, heading_title = len(heading.group(1)), heading.group(2).strip()
            if section_level is not None and level <= section_level:
                return (
                    (section_start or 0, index) if section_start is not None else None
                )
            if heading_title.casefold() == title.casefold() and section_start is None:
                section_level = level
                section_start = index + 1
    return (section_start, len(lines)) if section_start is not None else None


def _fence_start(line: str) -> tuple[str, int] | None:
    if not line or line[0] not in "`~":
        return None
    marker = line[0]
    width = len(line) - len(line.lstrip(marker))
    return (marker, width) if width >= 3 else None


def _fence_end(line: str, marker: str, width: int) -> bool:
    return (
        len(line) - len(line.lstrip(marker)) >= width
        and not line.lstrip(marker).strip()
    )


def json_merge_state(record: Mapping[str, object], facts: StatusFacts) -> str:
    if not record.get("merge_approved_at"):
        return "absent"
    identifier = str(record.get("id", ""))
    branch = record.get("branch") or f"worktree/{identifier}"
    if not isinstance(branch, str) or not branch or branch not in facts.branches:
        return "unknown"
    return "merged" if branch in facts.merged else "approved_not_merged"


def awaiting_user_message(
    record: Mapping[str, object],
    messages: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
) -> Mapping[str, object] | None:
    assigned_to = record.get("assigned_to")
    if (
        not isinstance(assigned_to, str)
        or not assigned_to
        or classify_status(str(record.get("status", ""))) == "terminal"
    ):
        return None
    pending = None
    for message in messages:
        if (
            message.get("from") == assigned_to
            and message.get("to") == "main"
            and message.get("kind") in {"needs-user", "merge-ready"}
        ):
            pending = message
        elif (
            message.get("from") in {"main", "dashboard"}
            and message.get("to") == assigned_to
        ):
            pending = None
    return pending


def stalled_detail(
    record: Mapping[str, object],
    tasks: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    messages: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    facts: StatusFacts,
) -> str | None:
    assigned_to = record.get("assigned_to")
    if not isinstance(assigned_to, str) or not assigned_to:
        return None
    if awaiting_user_message(record, messages) is not None:
        return None
    if not any(
        classify_status(str(task.get("status", ""))) != "terminal" for task in tasks
    ):
        return None
    binding = next(
        (item for item in facts.bindings if item.address == assigned_to), None
    )
    if binding is None or binding.last_seen is None:
        return None
    try:
        last_seen = datetime.fromisoformat(binding.last_seen).timestamp()
    except ValueError:
        return None
    idle = max(0, int(facts.clock - last_seen))
    activity_text = datetime.fromtimestamp(last_seen, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    owner_message = False
    for message in messages:
        timestamp = message.get("ts")
        if (
            message.get("from") == record.get("id")
            and isinstance(timestamp, str)
            and timestamp > activity_text
        ):
            owner_message = True
            break
    if idle < 10 * 60 or owner_message:
        return None
    return f"stalled; idle {idle // 60}m with open work and no hand-back"


def _string_sequence(value: object) -> tuple[str, ...] | list[str]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        return [item for item in value if isinstance(item, str)]
    return ()


def _task_ready(task: TaskRecord, tasks: tuple[TaskRecord, ...]) -> bool:
    status = _task_status(task)
    if classify_status(status) == "terminal" or status in TASK_ACTIVE:
        return False
    dependencies = task.fields.get("depends_on", [])
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    if not isinstance(dependencies, list):
        return True
    return all(
        all(
            classify_status(_task_status(candidate)) == "terminal"
            for candidate in tasks
            if candidate.id == dependency
            or candidate.path.rsplit("/", 1)[-1].removesuffix(".md") == dependency
        )
        for dependency in dependencies
        if isinstance(dependency, str)
    )


def _task_status(task: TaskRecord) -> str:
    value = task.fields.get("status")
    return value if isinstance(value, str) else "todo"


def _task_title(task: TaskRecord) -> str:
    value = task.fields.get("title")
    return (
        value
        if isinstance(value, str)
        else task.path.rsplit("/", 1)[-1].removesuffix(".md")
    )


def _task_state_label(state: str) -> str:
    return "in review" if state == "in_review" else state.replace("_", " ")


def dependency_order(
    plans: tuple[PlanRecord, ...] | list[PlanRecord],
) -> list[PlanRecord]:
    remaining = sorted(plans, key=lambda plan: (plan.id, plan.path))
    ordered: list[PlanRecord] = []
    while remaining:
        index = next(
            (
                index
                for index, plan in enumerate(remaining)
                if not any(
                    dependency in {other.id for other in remaining}
                    for dependency in plan.depends_on
                )
            ),
            None,
        )
        if index is None:
            ordered.extend(remaining)
            break
        ordered.append(remaining.pop(index))
    return ordered


def path_sort_key(identifier: str) -> tuple[int, str, str]:
    prefix = identifier[:10]
    dated = (
        bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", prefix))
        and len(identifier) > 10
        and identifier[10] == "-"
    )
    return (
        0 if dated else 1,
        f"{-int(prefix.replace('-', '')):08d}" if dated else identifier,
        identifier,
    )
