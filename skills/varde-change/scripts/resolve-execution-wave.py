#!/usr/bin/env python3
"""Resolve one dependency-ready execution wave from a task manifest."""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
IMPACT_RESOURCE_PREFIX = "impact:"


class ManifestError(Exception):
    def __init__(self, message: str, code: str = "invalid_manifest") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Task:
    task_id: str
    status: str
    depends_on: frozenset[str]
    owner_paths: tuple[str, ...]
    resources: frozenset[str]
    impact_resources: frozenset[str]
    ownership_known: bool
    impact_known: bool


def require_list(value: Any, field: str, task_id: str) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestError(f"task {task_id!r} field {field!r} must be a list")
    return value


def normalize_path(value: Any, field: str, task_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"task {task_id!r} field {field!r} contains a blank path")
    path = value.replace("\\", "/")
    if path.startswith("/"):
        raise ManifestError(
            f"task {task_id!r} field {field!r} contains an absolute path"
        )
    path = posixpath.normpath(path)
    if path in ("", ".") or path == ".." or path.startswith("../"):
        raise ManifestError(
            f"task {task_id!r} field {field!r} contains a traversal path"
        )
    return str(PurePosixPath(path))


def rename_paths(value: Any, task_id: str) -> tuple[list[str], bool]:
    paths: list[str] = []
    complete = True
    for entry in require_list(value, "renames", task_id):
        if isinstance(entry, str):
            paths.append(normalize_path(entry, "renames", task_id))
            complete = False
            continue
        if not isinstance(entry, dict):
            raise ManifestError(f"task {task_id!r} contains an invalid rename")
        if "from" not in entry or "to" not in entry:
            complete = False
        for key in ("from", "to"):
            if key in entry:
                paths.append(normalize_path(entry[key], f"renames.{key}", task_id))
        if not any(key in entry for key in ("from", "to")):
            raise ManifestError(f"task {task_id!r} contains an empty rename")
    return paths, complete


def parse_dependencies(raw: dict[str, Any], task_id: str) -> frozenset[str]:
    dependencies = require_list(raw.get("depends_on", []), "depends_on", task_id)
    if not all(isinstance(item, str) and item for item in dependencies):
        raise ManifestError(f"task {task_id!r} has invalid dependencies")
    return frozenset(dependencies)


def parse_ownership(raw: dict[str, Any], task_id: str) -> tuple[tuple[str, ...], bool]:
    ownership_known = True
    owner_paths: list[str] = []
    for field in ("modifies", "creates"):
        if field not in raw:
            ownership_known = False
            continue
        owner_paths.extend(
            normalize_path(item, field, task_id)
            for item in require_list(raw[field], field, task_id)
        )
    if "renames" not in raw:
        ownership_known = False
    else:
        renamed, rename_complete = rename_paths(raw["renames"], task_id)
        owner_paths.extend(renamed)
        ownership_known = ownership_known and rename_complete
    return tuple(sorted(set(owner_paths))), ownership_known


def parse_resources(
    raw: dict[str, Any], task_id: str
) -> tuple[frozenset[str], frozenset[str], bool]:
    if "verification_resources" not in raw:
        return frozenset(), frozenset(), False
    values = require_list(
        raw["verification_resources"], "verification_resources", task_id
    )
    if not all(isinstance(item, str) and item for item in values):
        raise ManifestError(f"task {task_id!r} has invalid verification resources")
    resources = frozenset(values)
    impact_resources = frozenset(
        item
        for item in values
        if item.startswith(IMPACT_RESOURCE_PREFIX)
        and len(item) > len(IMPACT_RESOURCE_PREFIX)
    )
    return resources, impact_resources, bool(impact_resources)


def parse_task(raw: Any, index: int) -> Task:
    if not isinstance(raw, dict):
        raise ManifestError(f"task at index {index} must be an object")
    task_id = raw.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ManifestError(f"task at index {index} needs a non-empty id")
    status = raw.get("status", "todo")
    if status not in {"todo", "in_progress", "done", "blocked"}:
        raise ManifestError(f"task {task_id!r} has unknown status {status!r}")
    dependencies = parse_dependencies(raw, task_id)
    owner_paths, ownership_known = parse_ownership(raw, task_id)
    resources, impact_resources, impact_known = parse_resources(raw, task_id)
    ownership_known = ownership_known and "verification_resources" in raw

    return Task(
        task_id=task_id,
        status=status,
        depends_on=dependencies,
        owner_paths=owner_paths,
        resources=resources,
        impact_resources=impact_resources,
        ownership_known=ownership_known,
        impact_known=impact_known,
    )


def validate_dependencies(tasks: list[Task]) -> None:
    ids = [task.task_id for task in tasks]
    if len(set(ids)) != len(ids):
        raise ManifestError("task ids must be unique")
    known_ids = set(ids)
    for task in tasks:
        missing = task.depends_on - known_ids
        if missing:
            raise ManifestError(
                f"task {task.task_id!r} depends on missing task {sorted(missing)[0]!r}"
            )


def parse_worker_limits(manifest: dict[str, Any]) -> tuple[int, int]:
    capacity = manifest.get("harness_capacity", 2)
    maximum = manifest.get("max_parallel_workers", 2)
    if not isinstance(capacity, int) or capacity < 1:
        raise ManifestError("harness_capacity must be a positive integer")
    if not isinstance(maximum, int) or maximum < 1:
        raise ManifestError("max_parallel_workers must be a positive integer")
    if maximum > capacity:
        raise ManifestError(
            f"max_parallel_workers={maximum} exceeds harness capacity={capacity}",
            code="capacity_exceeded",
        )
    return capacity, maximum


def load_manifest(path: str) -> tuple[list[Task], int, int]:
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read manifest {path!r}: {error}") from error
    if not isinstance(manifest, dict):
        raise ManifestError("manifest root must be an object")
    raw_tasks = manifest.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ManifestError("manifest needs a non-empty tasks list")
    tasks = [parse_task(raw, index) for index, raw in enumerate(raw_tasks)]
    validate_dependencies(tasks)
    capacity, maximum = parse_worker_limits(manifest)
    return tasks, capacity, maximum


def path_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def task_conflict(left: Task, right: Task) -> str | None:
    if not left.ownership_known or not right.ownership_known:
        return "unknown-ownership"
    if not left.impact_known or not right.impact_known:
        return "unknown-impact"
    owns_same_path = any(
        path_overlap(left_path, right_path)
        for left_path in left.owner_paths
        for right_path in right.owner_paths
    )
    shares_resource = bool(left.resources & right.resources)
    shares_impact = bool(left.impact_resources & right.impact_resources)
    if owns_same_path and shares_resource:
        if shares_impact:
            return "ownership-and-impact"
        return "ownership-and-resource"
    if owns_same_path:
        return "ownership"
    if shares_impact:
        return "impact-resource"
    if shares_resource:
        return "verification-resource"
    return None


def find_conflicts(tasks: list[Task]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(tasks):
        for right in tasks[index + 1 :]:
            reason = task_conflict(left, right)
            if reason:
                conflicts.append(
                    {"tasks": [left.task_id, right.task_id], "reason": reason}
                )
    return conflicts


def select_wave(
    by_id: dict[str, Task],
    pending: set[str],
    completed: set[str],
    maximum: int,
) -> list[Task]:
    candidates = sorted(
        (
            by_id[task_id]
            for task_id in pending
            if by_id[task_id].depends_on <= completed
        ),
        key=lambda task: task.task_id,
    )
    if not candidates:
        blocked = sorted(pending)[0]
        raise ManifestError(
            f"task {blocked!r} is blocked by incomplete dependencies or a cycle",
            code="dependency_blocked",
        )
    wave: list[Task] = []
    for candidate in candidates:
        if len(wave) >= maximum:
            break
        if not any(task_conflict(candidate, selected) for selected in wave):
            wave.append(candidate)
    if not wave:
        raise ManifestError("no conflict-free task can enter the next wave")
    return wave


def build_waves(tasks: list[Task], maximum: int) -> tuple[list[str], list[list[str]]]:
    by_id = {task.task_id: task for task in tasks}
    completed = {task.task_id for task in tasks if task.status == "done"}
    pending = {
        task.task_id for task in tasks if task.status not in {"done", "blocked"}
    }
    initial_ready = sorted(
        task_id for task_id in pending if by_id[task_id].depends_on <= completed
    )

    waves: list[list[str]] = []
    while pending:
        wave = select_wave(by_id, pending, completed, maximum)
        wave_ids = [task.task_id for task in wave]
        waves.append(wave_ids)
        pending.difference_update(wave_ids)
        completed.update(wave_ids)
    return initial_ready, waves


def resolve(tasks: list[Task], capacity: int, maximum: int) -> dict[str, Any]:
    initial_ready, waves = build_waves(tasks, maximum)
    conflicts = find_conflicts(tasks)
    unknown = sorted(task.task_id for task in tasks if not task.ownership_known)
    unknown_impact = sorted(task.task_id for task in tasks if not task.impact_known)

    parallel_safe = not unknown and not unknown_impact and not conflicts
    return {
        "schema_version": SCHEMA_VERSION,
        "ready_tasks": initial_ready,
        "waves": waves,
        "conflicts": conflicts,
        "unknown_ownership": unknown,
        "unknown_impact": unknown_impact,
        "parallel_safe": parallel_safe,
        "capacity": capacity,
        "max_parallel_workers": maximum,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--strategy", choices=("auto", "parallel"))
    args = parser.parse_args()
    try:
        tasks, capacity, maximum = load_manifest(args.manifest)
        result = resolve(tasks, capacity, maximum)
    except ManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 3 if error.code == "capacity_exceeded" else 2

    if args.strategy:
        first_wave_size = len(result["waves"][0]) if result["waves"] else 0
        if args.strategy == "parallel":
            if not result["parallel_safe"] or first_wave_size < 2:
                print(
                    "error: parallel requires at least two independent ready tasks",
                    file=sys.stderr,
                )
                return 2
            print("parallel")
        else:
            print(
                "parallel"
                if result["parallel_safe"] and first_wave_size > 1
                else "fresh"
            )
        return 0

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
