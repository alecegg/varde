"""Read-only progress rollup for configured working plans."""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, overload

from varde_data.plan_state_sync import export_plan_dir
from varde_data.plans import open_fresh_plans
from varde_data.queue_mode_lock import operation
from varde_data.records.plans import PlanRecord, TaskRecord
from varde_data.views import (
    StatusFacts,
    classify_status,
    merge_verdict,
    path_sort_key,
    plan_progress,
    task_progress,
)
from varde_data.views import (
    count_open_questions as view_count_open_questions,
)
from varde_data.views import (
    parse_status_at as view_parse_status_at,
)
from varde_data.views import (
    section_bullets as view_section_bullets,
)
from varde_data.views import (
    section_span as view_section_span,
)
from varde_data.views import (
    stalled_minutes as view_stalled_minutes,
)
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths
from varde_learn.knowledge.memory_config import load_config

from varde_workflow.collector_facts import (
    gather_collector_facts,
)
from varde_workflow.collectors import collect_status
from varde_workflow.errors import InternalError, report_error
from varde_workflow.execution_wave_paths import matches_declaration
from varde_workflow.execution_wave_tools import git
from varde_workflow.git_facts import (
    get_git_facts,
    reviewed_commit_facts,
)
from varde_workflow.merge_state import (
    awaiting_user,
    json_merge_state,
    local_branches,
    read_bindings,
    read_messages,
    read_plan_tasks,
    stalled_detail,
)
from varde_workflow.output import print_cli_success
from varde_workflow.plan_comments import open_comment_count
from varde_workflow.plan_labels import resolve_group, resolve_parent_group
from varde_workflow.schema import TASK_ACTIVE as ACTIVE_TASK_STATES

TASK_ACTIVE = set(ACTIVE_TASK_STATES)


def parse_status_at(value: str) -> float | None:
    return view_parse_status_at(value)


def status_bucket(status: str) -> str:
    return classify_status(status)


def _now_line_timestamp(plans_dir: Path, plan: Path) -> float | None:
    from varde_workflow.commands.now import line_paths

    timestamps = []
    for now_path in line_paths(plans_dir, plan):
        try:
            timestamps.append(now_path.stat().st_mtime)
        except OSError:
            continue
    return max(timestamps, default=None)


@overload
def _string(mapping: dict[str, Any], key: str, default: str) -> str: ...


@overload
def _string(mapping: dict[str, Any], key: str, default: None = None) -> str | None: ...


def _string(
    mapping: dict[str, Any], key: str, default: str | None = None
) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) else default


def artifact_type(mapping: dict[str, Any]) -> str:
    return _string(mapping, "artifact_type") or _string(mapping, "type") or "plan"


def artifact_id(path: Path, mapping: dict[str, Any]) -> str:
    return _string(mapping, "id") or (
        path.parent.name if path.name == "plan.md" else path.stem
    )


def string_list(mapping: dict[str, Any], key: str) -> list[str]:
    value = mapping.get(key)
    values = (
        value if isinstance(value, list) else [value] if isinstance(value, str) else []
    )
    return [item for item in values if isinstance(item, str) and item]


def collect_plan_paths(directory: Path, paths: list[Path], skipped: list[int]) -> None:
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError:
        skipped[0] += 1
        return
    for entry in entries:
        try:
            if entry.is_dir() and entry.name != "archive":
                collect_plan_paths(entry, paths, skipped)
            elif (
                entry.name == "plan.md"
                and (entry.is_file() or entry.is_symlink())
                or (
                    entry.name == "task.md"
                    and (entry.is_file() or entry.is_symlink())
                    and not (entry.parent / "plan.md").exists()
                )
            ):
                paths.append(entry)
        except OSError:
            skipped[0] += 1


def _parse(path: Path) -> tuple[dict[str, Any], str]:
    return parse(path.read_bytes())


def read_plan(
    path: Path, stall_minutes: int, parent_group: str = ""
) -> dict[str, Any] | None:
    try:
        mapping, body = _parse(path)
    except OSError, ValueError:
        return None
    kind = artifact_type(mapping)
    identifier = artifact_id(path, mapping)
    if path.name == "task.md" and kind == "task":
        task_status = _string(mapping, "status", "todo")
        title = _string(mapping, "title", path.parent.name)
        return {
            "id": path.parent.name,
            "status": task_status,
            "title": title,
            "label": _label(mapping, title),
            "group_name": "",
            "owner": None,
            "group": False,
            "questions": 0,
            "done": 0,
            "total": 0,
            "in_progress": False,
            "status_at": _string(mapping, "status_at"),
            "task_now": None,
            "depends": string_list(mapping, "depends_on"),
            "terminal": status_bucket(task_status) == "terminal",
            "merge": "none",
            "merge_state": "absent",
            "stalled": False,
            "now": None,
            "now_at": None,
        }
    if kind != "plan":
        return None
    tasks, skipped = _read_tasks(path, stall_minutes, mapping)
    status = _string(mapping, "status", "backlog")
    title = _string(mapping, "title", identifier)
    return {
        "id": identifier,
        "status": status,
        "title": title,
        "label": _label(mapping, title),
        "purpose": _plan_purpose(body),
        "group_name": resolve_group(mapping.get("group"), parent_group),
        "owner": _string(mapping, "owner"),
        "assigned_to": _string(mapping, "assigned_to"),
        "awaiting_user": None,
        "merge_approved_at": _string(mapping, "merge_approved_at"),
        "merge_state": "absent",
        "stalled": False,
        "branch": _string(mapping, "branch"),
        "group": mapping.get("shape") == "group",
        "questions": count_open_questions(body),
        "done": tasks["done"],
        "total": tasks["total"],
        "in_progress": tasks["in_progress"],
        "task_now": tasks["now"],
        "depends": string_list(mapping, "depends_on"),
        "terminal": status_bucket(status) == "terminal",
        "merge": _merge_state(path, status),
        "now": None,
        "now_at": None,
        "skipped": skipped,
    }


def _plan_purpose(body: str) -> str:
    """Return the first sentence in the plan's Problem section, capped at 140 chars."""
    match = re.search(r"(?ims)^##\s+Problem\s*\n(.*?)(?=^##\s+|\Z)", body)
    if match is None:
        return ""
    paragraph = re.sub(r"\s+", " ", match.group(1)).strip()
    sentence = re.split(r"(?<=[.!?])\s+", paragraph, maxsplit=1)[0]
    if len(sentence) <= 140:
        return sentence
    boundary = sentence[:140].rfind(" ")
    if boundary <= 0:
        boundary = 140
    return f"{sentence[:boundary].rstrip()}…"


def _read_tasks(
    plan: Path, stall_minutes: int, plan_fields: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    folder = plan.parent / "tasks"
    if not folder.is_dir():
        return {"done": 0, "total": 0, "in_progress": False, "now": None}, 0
    records: list[TaskRecord] = []
    skipped = 0
    try:
        entries = sorted(folder.iterdir(), key=lambda item: item.name)
    except OSError:
        return {"done": 0, "total": 0, "in_progress": False, "now": None}, 1
    for path in entries:
        if path.suffix != ".md" or not (path.is_file() or path.is_symlink()):
            continue
        try:
            raw = path.read_bytes()
            mapping, _ = parse(raw)
        except OSError, ValueError:
            skipped += 1
            continue
        if artifact_type(mapping) != "task":
            skipped += 1
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        records.append(
            TaskRecord(artifact_id(path, mapping), mapping, raw, mtime, str(path))
        )
    task_activity = {}
    for task in records:
        note = plan.parent / "notes" / f"{task.id}.md"
        with contextlib.suppress(OSError):
            task_activity[task.id] = note.stat().st_mtime
    plan_record = PlanRecord(
        _string(plan_fields, "id") or plan.parent.name,
        plan_fields,
        b"",
        0.0,
        str(plan),
        tuple(records),
    )
    return task_progress(
        plan_record,
        StatusFacts(
            time.time(), stall_minutes=stall_minutes, task_activity=task_activity
        ),
    ), skipped


def _label(mapping: dict[str, Any], title: str) -> str:
    label = _string(mapping, "label")
    return label.strip() if label and label.strip() else title


def count_open_questions(body: str) -> int:
    return view_count_open_questions(body)


def section_bullets(
    lines: list[str], start: int, end: int
) -> list[tuple[int, int, str]]:
    """Compatibility shim for the pure section bullet helper."""
    return view_section_bullets(lines, start, end)


def section_span(body: str, title: str) -> tuple[int, int] | None:
    """Compatibility shim for the pure section span helper."""
    return view_section_span(body, title)


def _merge_state(path: Path, status: str) -> str:
    try:
        mapping, _ = _parse(path.parent / "review.md")
    except OSError, ValueError:
        return "none"
    verdict = mapping.get("verdict")
    return merge_verdict(verdict if isinstance(verdict, str) else None, status)


def stalled_minutes(now: float, last_activity: float, threshold: int) -> int | None:
    return view_stalled_minutes(now, last_activity, threshold)


def collect_from(
    working: str | Path,
    now: float | None = None,
    stall_minutes: int = 60,
    repo: str | Path | None = None,
) -> dict[str, Any]:
    working = Path(working)
    plans_dir = working / "plans"
    paths: list[Path] = []
    skipped = [0]
    if plans_dir.is_dir():
        collect_plan_paths(plans_dir, paths, skipped)
    from varde_workflow.commands.now import read_line

    repository = Path(repo or Path.cwd())
    timestamp = time.time() if now is None else now

    records: dict[Path, dict[str, Any]] = {}
    bindings = read_bindings(working)
    discovered = set(paths)
    parent_groups: dict[Path, str] = {}
    messages: list[Mapping[str, object]] | None = None
    existing = local_branches(repository)
    ordered_paths = sorted(
        paths, key=lambda item: (len(item.parts), path_sort_key(item.parent.name))
    )
    for path in ordered_paths:
        parent_path = _parent_plan(path, plans_dir, discovered)
        ancestor_groups = []
        while parent_path is not None:
            ancestor_groups.append(parent_groups.get(parent_path))
            parent_path = _parent_plan(parent_path, plans_dir, discovered)
        inherited_group = resolve_parent_group(ancestor_groups)
        record = read_plan(path, stall_minutes, inherited_group)
        if record is None:
            skipped[0] += 1
            continue
        record["merge_state"] = json_merge_state(record, repository, existing)
        if path.name == "plan.md":
            record["awaiting_user"] = awaiting_user(record, working)
        if path.name == "plan.md" and record.get("assigned_to"):
            if messages is None:
                messages = read_messages(working)
            record["stalled"] = (
                stalled_detail(
                    record,
                    read_plan_tasks(path.parent),
                    bindings,
                    working,
                    timestamp,
                    messages,
                )
                is not None
            )
        record["path"] = str(path)
        record["now"] = read_line(plans_dir, path)
        now_timestamp = _now_line_timestamp(plans_dir, path)
        record["now_at"] = (
            datetime.fromtimestamp(now_timestamp).astimezone().isoformat()
            if now_timestamp is not None
            else None
        )
        skipped[0] += record.pop("skipped", 0)
        records[path] = record
        if path.name == "plan.md":
            parent_groups[path] = record["group_name"]
    children: dict[Path, list[Path]] = {}
    roots = []
    for path in records:
        parent = _parent_plan(path, plans_dir, set(records))
        if parent:
            children.setdefault(parent, []).append(path)
        else:
            roots.append(path)
    by_key = {str(path): record for path, record in records.items()}
    view_children = {
        str(path): [str(child) for child in values] for path, values in children.items()
    }
    progress = plan_progress(by_key, view_children, [str(path) for path in roots])
    return add_open_comments({**progress, "skipped": skipped[0]}, working)


def add_open_comments(
    report: dict[str, Any],
    working: Path,
    plan_records: tuple[PlanRecord, ...] | None = None,
) -> dict[str, Any]:
    """Add per-plan and total open-comment counts to a status report."""
    counts: dict[str, int] = {}
    if plan_records is not None:
        counts = {
            record.id: open_comment_count(Path(record.path))
            for record in plan_records
            if record.artifact_type == "plan"
        }
    else:
        plans_dir = working / "plans"
        for plan_path in plans_dir.rglob("plan.md"):
            try:
                metadata, _ = parse(plan_path.read_bytes())
            except OSError, ValueError:
                continue
            counts[artifact_id(plan_path, metadata)] = open_comment_count(plan_path)
    _add_open_comments(report.get("plans", []), counts)
    report["open_comments"] = sum(counts.values())
    return report


def _add_open_comments(plans: list[dict[str, Any]], counts: dict[str, int]) -> None:
    for plan in plans:
        plan["open_comments"] = counts.get(str(plan.get("id", "")), 0)
        _add_open_comments(plan.get("children", []), counts)


def _parent_plan(path: Path, plans_dir: Path, paths: set[Path]) -> Path | None:
    directory = path.parent
    while directory.is_relative_to(plans_dir):
        candidate = directory / "plan.md"
        if candidate != path and candidate in paths:
            return candidate
        if directory == plans_dir:
            break
        directory = directory.parent
    return None


def render(report: dict[str, Any], time_text: str) -> str:
    lines = [f"**Progress** {time_text}"]
    if not report["plans"] and not report["backlog_count"]:
        lines.append("No plans in a non-terminal status.")
    else:
        for index, plan in enumerate(report["plans"]):
            _render_plan(plan, str(index + 1), 0, lines)
        if report["more_count"]:
            lines.append(f"+{report['more_count']} more")
    if report["backlog_count"]:
        lines.append(f"+{report['backlog_count']} backlog")
    if report.get("open_comments"):
        count = report["open_comments"]
        plural = "s" if count != 1 else ""
        lines.append(f"{count} open comment{plural} across plans")
    if report["skipped"]:
        lines.append(
            f"Skipped {report['skipped']} file(s): unknown artifact type or unreadable."
        )
    return "\n".join([*lines, ""])


def _render_plan(
    plan: dict[str, Any], label: str, depth: int, lines: list[str]
) -> None:
    indent = "   " * depth
    bullet = "- " if depth else ""
    owner = f" (owner: {plan['owner']})" if plan.get("owner") else ""
    progress = (
        f" (group) {plan['done']}/{plan['total']} plans"
        if plan["group"] and plan["total"]
        else f" {plan['done']}/{plan['total']}"
        if plan["total"]
        else ""
    )
    open_comments = plan.get("open_comments", 0)
    comments = (
        f"; {open_comments} open comment{'s' if open_comments != 1 else ''}"
        if open_comments
        else ""
    )
    lines.append(
        f"{indent}{bullet}{label}. {plan['id']}{owner}{progress}{comments}: "
        f"{plan['now']}"
    )
    for index, child in enumerate(plan["children"]):
        suffix = _alpha_label(index)
        _render_plan(child, label + suffix, depth + 1, lines)
    if plan["more_count"]:
        lines.append(f"{'   ' * (depth + 1)}+{plan['more_count']} more")


def _alpha_label(index: int) -> str:
    label = ""
    while True:
        label = chr(ord("a") + index % 26) + label
        if index < 26:
            return label
        index = index // 26 - 1


def _resolve_repo(repo: str | Path | None) -> Path | None:
    if repo is not None:
        return Path(repo).resolve(strict=False)
    found = git(Path.cwd(), ["rev-parse", "--show-toplevel"])
    return (
        Path(found[1].strip()) if found and found[0] == 0 and found[1].strip() else None
    )


def staleness_notice_for(
    plan_path: str | Path, repo: str | Path | None = None
) -> str | None:
    repository = _resolve_repo(repo)
    if repository is None:
        return None
    try:
        mapping, _ = _parse(Path(plan_path))
    except OSError, ValueError:
        return None
    status_value = _string(mapping, "status", "backlog")
    if status_bucket(status_value) == "terminal":
        return None
    reviewed = mapping.get("reviewed_commit")
    if not isinstance(reviewed, str) or not reviewed:
        return None
    identifier = artifact_id(Path(plan_path), mapping)
    exists = git(repository, ["cat-file", "-e", f"{reviewed}^{{commit}}"])
    if not exists or exists[0] != 0:
        return f"review commit {reviewed} not found in {repository}"
    try:
        reviewed_date = datetime.strptime(
            str(mapping.get("reviewed_on", "")), "%Y-%m-%d"
        ).date()
        days = max(0, (datetime.now().date() - reviewed_date).days)
    except ValueError:
        days = 0
    patterns = (
        [item for item in mapping.get("shared", []) if isinstance(item, str)]
        if isinstance(mapping.get("shared", []), list)
        else []
    )
    tasks_dir = Path(plan_path).parent / "tasks"
    if tasks_dir.is_dir():
        for task in sorted(tasks_dir.glob("*.md")):
            try:
                task_mapping, _ = _parse(task)
            except OSError, ValueError:
                continue
            for key in ("owns", "modifies", "creates"):
                patterns.extend(
                    item for item in task_mapping.get(key, []) if isinstance(item, str)
                ) if isinstance(task_mapping.get(key, []), list) else None
            renames = task_mapping.get("renames", [])
            if isinstance(renames, list):
                for rename in renames:
                    if isinstance(rename, str) and "->" in rename:
                        patterns.extend(
                            piece.strip() for piece in rename.split("->", 1)
                        )
    patterns = sorted(set(patterns))
    if not patterns:
        return f"review of {identifier} is {days} days old" if days > 7 else None
    result = git(repository, ["log", "--format=%H", "--name-only", f"{reviewed}..HEAD"])
    commits = 0
    if result and result[0] == 0:
        touched = False
        for iter_line in result[1].splitlines():
            line = iter_line.strip()
            if not line:
                continue
            if re.fullmatch(r"[0-9a-fA-F]{40}", line):
                commits += int(touched)
                touched = False
            elif not touched and any(
                matches_declaration(pattern, line) for pattern in patterns
            ):
                touched = True
        commits += int(touched)
    if commits == 0 and days <= 7:
        return None
    return (
        f"review of {identifier} is {days} days old; {commits} commits since "
        "touched its scope"
    )


def staleness_notices_index(repo_handle: Any, repo: Path) -> list[str]:
    """Build review staleness notices from indexed metadata and cached Git facts."""
    tasks_by_plan: dict[str, list[dict[str, Any]]] = {}
    for row in repo_handle.task_rows():
        if row.get("archived"):
            continue
        tasks_by_plan.setdefault(str(row["plan_path"]), []).append(
            json.loads(str(row["frontmatter_json"]))
        )
    notices = []
    for row in repo_handle.plan_rows():
        if row.get("archived"):
            continue
        fields = json.loads(str(row["frontmatter_json"]))
        if status_bucket(str(row.get("status") or "backlog")) == "terminal":
            continue
        reviewed = fields.get("reviewed_commit")
        if not isinstance(reviewed, str) or not reviewed:
            continue
        path = Path(str(row["path"]))
        try:
            reviewed_date = datetime.strptime(
                str(fields.get("reviewed_on", "")), "%Y-%m-%d"
            ).date()
            days = max(0, (datetime.now().date() - reviewed_date).days)
        except ValueError:
            days = 0
        review_facts = reviewed_commit_facts(repo, reviewed)
        if not review_facts.exists:
            notices.append(f"review commit {reviewed} not found in {repo}")
            continue
        shared = fields.get("shared", [])
        patterns = (
            [item for item in shared if isinstance(item, str)]
            if isinstance(shared, list)
            else []
        )
        for task in tasks_by_plan.get(str(path), []):
            for key in ("owns", "modifies", "creates"):
                values = task.get(key, [])
                if isinstance(values, list):
                    patterns.extend(item for item in values if isinstance(item, str))
            renames = task.get("renames", [])
            if isinstance(renames, list):
                for rename in renames:
                    if isinstance(rename, str) and "->" in rename:
                        patterns.extend(
                            piece.strip() for piece in rename.split("->", 1)
                        )
        identifier = str(row["id"])
        patterns = sorted(set(patterns))
        if not patterns:
            if days > 7:
                notices.append(f"review of {identifier} is {days} days old")
            continue
        commits = sum(
            any(
                matches_declaration(pattern, touched)
                for pattern in patterns
                for touched in paths
            )
            for paths in review_facts.commits
        )
        if commits or days > 7:
            notices.append(
                f"review of {identifier} is {days} days old; {commits} commits since "
                "touched its scope"
            )
    return notices


def staleness_notices(working: Path, repo: str | Path | None = None) -> list[str]:
    repository = _resolve_repo(repo)
    if repository is None:
        return []
    paths: list[Path] = []
    skipped = [0]
    plans_dir = working / "plans"
    if plans_dir.is_dir():
        collect_plan_paths(plans_dir, paths, skipped)
    return [
        notice for path in paths if (notice := staleness_notice_for(path, repository))
    ]


def load_stall_minutes() -> tuple[int, str | None]:
    default = 60
    try:
        config = load_config()
        raw = config.orchestration.values.get("stall_minutes")
        if raw is None:
            result = (default, None)
        elif isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            result = (raw, None)
        else:
            result = (default, f"{raw!r} is not a positive integer")
    except Exception as exc:
        return default, f"could not load config ({exc})"
    else:
        return result


def plan_status_report(
    working: Path, repository: Path, stall_minutes: int
) -> tuple[dict[str, Any], Any]:
    """Build the plan status rollup; return it with the plan repository handle."""
    with operation(working) as mode:
        if mode == "sqlite":
            for plan_file in (working / "plans").rglob("plan.md"):
                export_plan_dir(working, plan_file.parent)
        repo_handle = open_fresh_plans(working)
        report = collect_status(
            repo_handle,
            gather_collector_facts(working, get_git_facts(repository, refresh=True)),
            stall_minutes=stall_minutes,
            working=working,
            repo=repository,
        )
    return report, repo_handle


def run(args: Any) -> int:
    threshold, notice = load_stall_minutes()
    if notice:
        print(
            (
                "varde plan status: orchestration stall_minutes ignored "
                f"({notice}); using {threshold}"
            ),
            file=__import__("sys").stderr,
        )
    try:
        working = MemoryPaths.resolve(Path.cwd()).working.path
        repository = Path(getattr(args, "repo", None) or Path.cwd()).resolve()
        report, repo_handle = plan_status_report(working, repository, threshold)
        report = add_open_comments(
            report, working, repo_handle.list(include_tasks=False).records
        )
        for item in staleness_notices_index(repo_handle, repository):
            print(item, file=__import__("sys").stderr)
        if args.json:
            print_cli_success(report)
        else:
            cache = working / ".cache" / "plan-status-last.txt"
            rendered = render(report, datetime.now().astimezone().strftime("%H:%M"))
            header, listing = rendered.split("\n", 1)
            try:
                previous = cache.read_text(encoding="utf-8")
            except OSError:
                previous = None
            cache.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                cache.write_text(listing, encoding="utf-8")
            print(
                f"{header}: no change since last check.\n"
                if previous == listing
                else rendered,
                end="",
            )
    except Exception as exc:
        return report_error(InternalError(str(exc)), args.json)
    else:
        return 0
