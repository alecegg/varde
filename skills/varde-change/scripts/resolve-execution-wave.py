#!/usr/bin/env python3
"""Pick the next execution wave for a plan's tasks.

Usage: resolve-execution-wave.py [--max-workers N] [--repo-root DIR] <plan-dir>

Reads task frontmatter (status, depends_on, modifies, creates, renames, and
verification_resources). A task's write set is modifies + creates + both paths
of each rename. Its reach is its write set plus `varde-code blast_radius` of
every existing modified or renamed path (transitive dependents). Two ready
tasks conflict when either writes into the other's reach or they share a
verification resource. `next_wave` is a greedy, id-ordered set of mutually
independent ready tasks, at most
--max-workers (default and ceiling 3), safe to run in parallel when it holds two
or more. Otherwise it is the first ready task alone. Without varde-code it
always holds one task. A modified or renamed path whose blast radius is empty or
fails is unknown, not independent: that task stays out of a multi-task wave.
Missing ownership metadata keeps `next_wave` to one task. The caller decides
how to execute it and may run fewer tasks together, never more.
Ownership and graph paths are compared after resolving symlink ancestors,
including new destinations. Unresolvable ownership keeps the whole wave serial.
Without Python's ALLOW_MISSING, dangling aliases or unresolved .. stay serial.

Output is JSON: ready, blocked_by_dep, next_wave, conflicts, reasons.
Exit codes: 0 ok, 1 usage or input error, 3 dependency cycle.
It dispatches nothing and writes nothing.
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

MAX_WORKERS = 3
LIST_KEYS = ("depends_on", "modifies", "creates", "renames", "verification_resources")
OWNERSHIP_KEYS = ("modifies", "creates", "renames", "verification_resources")


def parse_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not match:
        raise ValueError(f"{path}: missing frontmatter")
    data, key = {}, None
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key in LIST_KEYS:
            data[key].append(unquote(item.group(1)))
            continue
        field = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if not field:
            continue
        key, value = field.group(1), field.group(2).strip()
        if key in LIST_KEYS:
            inner = value[1:-1] if value.startswith("[") and value.endswith("]") else value
            data[key] = [unquote(v) for v in inner.split(",") if unquote(v)]
        else:
            data[key] = unquote(value)
    return data


def unquote(value):
    return value.strip().strip("'\"").strip()


def load_tasks(plan_dir):
    tasks = {}
    for path in sorted((plan_dir / "tasks").glob("*.md")):
        fm = parse_frontmatter(path)
        rename_paths = []
        invalid_renames = []
        for rename in fm.get("renames", []):
            parts = rename.split("->")
            if len(parts) != 2 or not all(part.strip() for part in parts):
                invalid_renames.append(rename)
                continue
            rename_paths.extend(norm(part) for part in parts)
        missing_ownership = [key for key in OWNERSHIP_KEYS if key not in fm]
        if invalid_renames:
            missing_ownership.append('renames (expected "old/path -> new/path")')
        tasks[path.stem] = {
            "status": fm.get("status", "todo"),
            "depends_on": fm.get("depends_on", []),
            "writes": sorted(set(
                [norm(p) for p in fm.get("modifies", []) + fm.get("creates", [])]
                + rename_paths
            )),
            "modifies": [norm(p) for p in fm.get("modifies", [])],
            "graph_sources": [norm(p) for p in fm.get("modifies", [])] + rename_paths,
            "verification_resources": sorted(set(fm.get("verification_resources", []))),
            "missing_ownership": missing_ownership,
        }
    return tasks


def norm(path):
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def canonical_path(repo_root, path):
    candidate = repo_root / path
    allow_missing = getattr(os.path, "ALLOW_MISSING", None)
    if allow_missing is not None:
        resolved = Path(os.path.realpath(candidate, strict=allow_missing))
    else:
        resolved = resolve_missing_compat(candidate)
    return resolved.relative_to(repo_root).as_posix()


def resolve_missing_compat(candidate):
    """Append only an unambiguous missing suffix on older Python."""
    ancestor = candidate
    suffix = []
    while True:
        try:
            return ancestor.resolve(strict=True).joinpath(*reversed(suffix))
        except FileNotFoundError:
            if ancestor.name == "..":
                raise ValueError(f"unresolved parent traversal in {candidate}")
            try:
                if stat.S_ISLNK(ancestor.lstat().st_mode):
                    raise ValueError(f"unresolved symlink in {candidate}")
            except FileNotFoundError:
                pass
            suffix.append(ancestor.name)
            ancestor = ancestor.parent


def find_cycle(tasks):
    state = {}

    def visit(tid):
        state[tid] = "open"
        for dep in tasks[tid]["depends_on"]:
            if dep not in tasks:
                continue
            if state.get(dep) == "open" or (dep not in state and visit(dep)):
                return True
        state[tid] = "closed"
        return False

    return any(tid not in state and visit(tid) for tid in tasks)


def blast_radius(repo_root, path):
    payload = json.dumps({"repoRoot": str(repo_root), "filePath": path, "fullResults": True})
    try:
        proc = subprocess.run(
            ["varde-code", "blast_radius", "--json", payload],
            capture_output=True, text=True, timeout=120,
        )
        result = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    if not result.get("ok") or not isinstance(result.get("data"), list):
        return None
    # Graph results and write sets must use the same repository-relative identity.
    try:
        return [canonical_path(repo_root, path) for path in result["data"]]
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def resolve(tasks, repo_root, max_workers):
    reasons, conflicts = [], []
    ready = [
        tid for tid, t in tasks.items()
        if t["status"] == "todo"
        and all(tasks.get(d, {}).get("status") == "done" for d in t["depends_on"])
    ]
    blocked_by_dep = []
    for tid, t in tasks.items():
        if t["status"] != "todo":
            continue
        for d in t["depends_on"]:
            dep = tasks.get(d)
            if dep is None or dep["status"] == "blocked":
                why = "missing" if dep is None else "blocked"
                blocked_by_dep.append({"task": tid, "dependency": d, "reason": why})
                reasons.append(f"{tid}: dependency {d} is {why}")
    have_cli = shutil.which("varde-code") is not None
    if not have_cli:
        reasons.append("varde-code unavailable: independence cannot be checked")

    missing_ownership = False
    writes_by_task, graph_sources = {}, {}
    for tid in ready:
        missing = tasks[tid]["missing_ownership"]
        if missing:
            missing_ownership = True
            reasons.append(f"{tid}: missing ownership metadata: {', '.join(missing)}")
            continue
        try:
            writes_by_task[tid] = {canonical_path(repo_root, path) for path in tasks[tid]["writes"]}
            graph_sources[tid] = {canonical_path(repo_root, path) for path in tasks[tid]["graph_sources"]}
        except (OSError, RuntimeError, ValueError) as exc:
            missing_ownership = True
            reasons.append(f"{tid}: ownership path identity is uncertain: {exc}")
            writes_by_task.pop(tid, None)

    reach, candidates = {}, []
    for tid in ready:
        if tid not in writes_by_task:
            continue
        writes = writes_by_task[tid]
        if not writes:
            reasons.append(f"{tid}: empty modifies/creates/renames")
            continue
        if not have_cli:
            continue
        area = set(writes)
        for path in sorted(graph_sources[tid]):
            if not (repo_root / path).exists():
                continue
            found = blast_radius(repo_root, path)
            if not found:
                # Empty is indistinguishable from an unindexed language.
                why = "failed" if found is None else "found no graph edges"
                reasons.append(f"{tid}: blast_radius {why} for {path}")
                area = None
                break
            area.update(found)
        if area is not None:
            reach[tid] = area
            candidates.append(tid)

    wave = []
    for tid in candidates:
        clash = None
        for other in wave:
            shared = (writes_by_task[tid] & reach[other]) | (writes_by_task[other] & reach[tid])
            shared_resources = (
                set(tasks[tid]["verification_resources"])
                & set(tasks[other]["verification_resources"])
            )
            if shared or shared_resources:
                clash = other
                conflicts.append({
                    "tasks": [other, tid],
                    "files": sorted(shared),
                    "resources": sorted(shared_resources),
                })
                break
        if clash is None and len(wave) < max_workers:
            wave.append(tid)

    if len(wave) < 2 or missing_ownership:
        wave = ready[:1]
    return {
        "schema_version": 3,
        "ready": ready,
        "blocked_by_dep": blocked_by_dep,
        "next_wave": wave,
        "conflicts": conflicts,
        "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("plan_dir", type=Path)
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args()

    if not (args.plan_dir / "tasks").is_dir():
        print(f"error: {args.plan_dir}/tasks is not a directory", file=sys.stderr)
        return 1
    if not 1 <= args.max_workers <= MAX_WORKERS:
        print(f"error: --max-workers must be 1..{MAX_WORKERS}", file=sys.stderr)
        return 1
    repo_root = args.repo_root
    if repo_root is None:
        proc = subprocess.run(
            ["git", "-C", str(args.plan_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        repo_root = Path(proc.stdout.strip() or ".")

    try:
        tasks = load_tasks(args.plan_dir)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if find_cycle(tasks):
        print("error: depends_on contains a cycle", file=sys.stderr)
        return 3

    result = resolve(tasks, repo_root.resolve(), args.max_workers)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
