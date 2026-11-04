"""Advisory execution waves from task ownership and code dependency reach."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_learn.knowledge.cmdbase.errors import ExitCode
from varde_learn.knowledge.frontmatter import parse

from . import execution_wave_tools as tools
from .execution_wave_paths import (
    canonical_declaration,
    declarations_overlap,
    matches_declaration,
)
from .task_ownership import OwnershipDeclarations


class WaveError(Exception, ExitCode):
    def __init__(self, message: str, cycle: bool = False):
        super().__init__(message)
        self.cycle = cycle

    def error_code(self) -> str:
        return "dependency_cycle" if self.cycle else "invalid_input"

    def exit_code(self) -> int:
        return 3 if self.cycle else 1


OWNERSHIP = ("owns", "modifies", "creates", "renames")


def _list(fm: dict[str, Any], key: str) -> list[str]:
    value = fm.get(key, [])
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{key} must be a list of strings")
    return value


def _norm(path: str) -> str:
    return path.strip().removeprefix("./")


def _load_tasks(plan: Path) -> dict[str, dict[str, Any]]:
    directory = plan / "tasks"
    if not directory.is_dir():
        raise ValueError(f"{plan}/tasks is not a directory")
    tasks = {}
    for path in sorted(directory.glob("*.md")):
        try:
            fm, body = parse(path.read_bytes())
        except Exception as error:
            raise ValueError(f"{path}: {error}") from error
        owns, modifies, creates = (
            set(map(_norm, _list(fm, "owns"))),
            list(map(_norm, _list(fm, "modifies"))),
            set(map(_norm, _list(fm, "creates"))),
        )
        renames, warnings = set(), []
        for rename in _list(fm, "renames"):
            parts = rename.split("->")
            if len(parts) != 2 or any(not x.strip() for x in parts):
                warnings.append('renames (expected "old/path -> new/path")')
                continue
            old, new = map(_norm, parts)
            renames.update((old, new))
            creates.add(new)
        status = fm.get("status", "todo")
        if not isinstance(status, str):
            raise TypeError(f"{path}: status must be a string")
        declared = any(key in fm for key in OWNERSHIP)
        tasks[path.stem] = {
            "status": status,
            "dependencies": _list(fm, "depends_on"),
            "owns": owns,
            "modifies": modifies,
            "creates": creates,
            "renames": renames,
            "body": body,
            "writes": owns | set(modifies) | creates | renames,
            "sources": {
                p for p in owns | set(modifies) if "*" not in p and not p.endswith("/")
            }
            | renames,
            "markdown": {
                p
                for p in owns | set(modifies)
                if p.lower().endswith(".md") and "*" not in p and not p.endswith("/")
            },
            "missing": warnings
            or ([] if declared else ["owns (or legacy modifies/creates/renames)"]),
        }
    return tasks


def ownership_declarations(plan: Path) -> list[tuple[str, str, OwnershipDeclarations]]:
    if not (plan / "tasks").exists():
        return []
    tasks = _load_tasks(plan)
    shared: set[str] = set()
    plan_file = plan / "plan.md"
    if plan_file.exists():
        fm, _ = parse(plan_file.read_bytes())
        shared = set(map(_norm, _list(fm, "shared") + _list(fm, "generated")))
    result = []
    for task_id, task in tasks.items():
        owned = set(task["modifies"]) | (task["renames"] - task["creates"])
        result.append(
            (
                task_id,
                task["status"],
                OwnershipDeclarations(
                    owned, set(task["owns"]), set(task["creates"]), shared
                ),
            )
        )
    return result


def derived_scope(plan: Path) -> set[str]:
    """Union of task owns, modifies and creates; rename paths are ignored."""
    if not (plan / "tasks").exists():
        return set()
    scope: set[str] = set()
    for task in _load_tasks(plan).values():
        scope |= (set(task["owns"]) | set(task["modifies"]) | task["creates"]) - task[
            "renames"
        ]
    return scope


def dependency_chain(dependencies: dict[str, list[str]]) -> bool:
    """True when every pair of tasks is ordered by transitive depends_on."""

    def reach(task_id: str, seen: frozenset[str] = frozenset()) -> frozenset[str]:
        found = set(seen)
        for dep in dependencies.get(task_id, []):
            if dep in dependencies and dep not in found:
                found.add(dep)
                found |= reach(dep, frozenset(found))
        return frozenset(found)

    reached = {task_id: reach(task_id) for task_id in dependencies}
    if any(task_id in found for task_id, found in reached.items()):
        return False
    ids = list(dependencies)
    return all(
        a in reached[b] or b in reached[a]
        for index, a in enumerate(ids)
        for b in ids[index + 1 :]
    )


def serial_plan(plan: Path) -> bool:
    """A plan is serial when its task files form a total depends_on chain."""
    try:
        tasks = _load_tasks(plan)
    except OSError, TypeError, ValueError:
        return False
    return bool(tasks) and dependency_chain(
        {task_id: task["dependencies"] for task_id, task in tasks.items()}
    )


def _cycle(tasks: dict[str, dict[str, Any]]) -> bool:
    visiting, visited = set(), set()

    def visit(task_id: str) -> bool:
        if task_id in visited:
            return False
        if task_id in visiting:
            return True
        visiting.add(task_id)
        for dep in tasks[task_id]["dependencies"]:
            if dep in tasks and visit(dep):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    return any(visit(task_id) for task_id in tasks)


def _mentions(body: str, path: str) -> bool:
    spellings = {path, "./" + path}
    parts = path.split("/")
    if "references" in parts:
        spellings.add("/".join(parts[parts.index("references") :]))
    for spelling in spellings:
        start = 0
        while (index := body.find(spelling, start)) >= 0:
            before = body[index - 1] if index else ""
            after = (
                body[index + len(spelling)] if index + len(spelling) < len(body) else ""
            )
            if not (before.isalnum() or before in "_.-/") and not (
                after.isalnum() or after in "_.-"
            ):
                return True
            start = index + 1
    return False


def _canonical_set(root: Path, paths: set[str]) -> set[str]:
    return {canonical_declaration(root, path) for path in paths}


def _overlap(left: set[str], right: set[str]) -> set[str]:
    result = set()
    for a in left:
        for b in right:
            if declarations_overlap(a, b):
                result.add(
                    a
                    if not any(c in a for c in "*?") and matches_declaration(b, a)
                    else b
                    if not any(c in b for c in "*?") and matches_declaration(a, b)
                    else a
                )
    return result


def execution_wave(
    plan: Path, root: Path, workers: int, impact: Any = None
) -> dict[str, Any]:
    if workers < 1:
        raise WaveError(
            "--max-workers must be at least 1; omit --max-workers to use "
            "[orchestration] builders"
        )
    tasks = _load_tasks(plan)
    if _cycle(tasks):
        raise WaveError("depends_on contains a cycle", cycle=True)
    root = root.resolve()
    if not root.is_dir():
        raise WaveError("repo root is not a directory")
    ready = [
        i
        for i, t in tasks.items()
        if t["status"] == "todo"
        and all(tasks.get(d, {}).get("status") == "done" for d in t["dependencies"])
    ]
    reasons, blocked = [], []
    for task_id, task in tasks.items():
        if task["status"] != "todo":
            continue
        for dep in task["dependencies"]:
            why = (
                "missing"
                if dep not in tasks
                else "blocked"
                if tasks[dep]["status"] == "blocked"
                else None
            )
            if why:
                blocked.append({"task": task_id, "dependency": dep, "reason": why})
                reasons.append(f"{task_id}: dependency {dep} is {why}")
    held = set()
    for task_id in ready:
        for creator, task in tasks.items():
            if creator != task_id and task["status"] != "done":
                for path in task["creates"]:
                    if _mentions(tasks[task_id]["body"], path):
                        held.add(task_id)
                        reasons.append(
                            f"{task_id}: mentions {path} created by {creator}; "
                            "add depends_on"
                        )
    if impact is None and len(ready) > 1:
        reasons.append("varde map unavailable: independence cannot be checked")
    uncertain, writes, sources, markdown, renames = False, {}, {}, {}, {}
    for task_id in ready:
        task = tasks[task_id]
        if any(
            "*" in p or p.endswith("/")
            for p in task["modifies"] + list(task["renames"])
        ):
            uncertain = True
            reasons.append(
                f"{task_id}: source ownership pattern has unknown dependency reach"
            )
        if task["missing"]:
            uncertain = True
            reasons.append(
                f"{task_id}: missing ownership metadata: {', '.join(task['missing'])}"
            )
            continue
        try:
            writes[task_id] = _canonical_set(root, task["writes"])
            sources[task_id] = _canonical_set(root, task["sources"])
            markdown[task_id] = _canonical_set(root, task["markdown"])
            renames[task_id] = _canonical_set(root, task["renames"])
        except (OSError, ValueError) as error:
            uncertain = True
            reasons.append(f"{task_id}: ownership path identity is uncertain: {error}")
    reach, candidates = {}, []
    for task_id in ready:
        if task_id in held or task_id not in writes:
            continue
        owned = writes[task_id]
        if not owned:
            reasons.append(f"{task_id}: empty ownership declarations")
            continue
        if impact is None:
            continue
        area, known = set(owned), True
        for path in sources[task_id]:
            if not (root / path).exists():
                continue
            found = tools.blast_radius(impact, root, path)
            if found is None:
                reasons.append(
                    f"{task_id}: blast_radius failed for {path} "
                    "(impact query unavailable; no code index exists: run "
                    "`varde map build`, then check "
                    "`varde map packs status`)"
                )
                known = False
                break
            if found:
                area.update(found)
            elif path not in markdown[task_id] or path in renames[task_id]:
                refs = tools.basename_references(root, path)
                if refs is None:
                    reasons.append(f"{task_id}: git grep failed for {path}")
                    known = False
                    break
                area.update(refs)
        if known:
            reach[task_id] = area
            candidates.append(task_id)
    conflicts = {}
    for ix, left in enumerate(ready):
        for right in ready[ix + 1 :]:
            if left in writes and right in writes:
                files = _overlap(writes[left], writes[right])
                if files:
                    conflicts[(left, right)] = files
    wave = []
    for task_id in candidates:
        clash = False
        for other in wave:
            shared = _overlap(writes[task_id], reach[other]) | _overlap(
                writes[other], reach[task_id]
            )
            if shared:
                conflicts.setdefault((other, task_id), set()).update(shared)
                clash = True
                break
        if not clash and len(wave) < workers:
            wave.append(task_id)
    if len(wave) < 2 or uncertain:
        wave = [task_id for task_id in ready if task_id not in held][:1]
    return {
        "schema_version": 3,
        "ready": ready,
        "blocked_by_dep": blocked,
        "next_wave": wave,
        "wave_mode": "worktree" if wave else "single",
        "conflicts": [
            {"tasks": list(pair), "files": sorted(files)}
            for pair, files in sorted(conflicts.items())
        ],
        "reasons": reasons,
    }
