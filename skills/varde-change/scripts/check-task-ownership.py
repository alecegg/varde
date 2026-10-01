#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Compare a task's source commit with the paths the task declares it owns.

Usage: check-task-ownership.py --task <task.md> --commit <sha> [--repo-root DIR]

Declared set: `modifies` + `creates` + both sides of each `renames` entry
(`old/path -> new/path`), repo-relative, excluding the task file itself.
Actual set: `git diff-tree --no-commit-id --name-only --no-renames -r <sha>`.

Precondition: one source commit per task, the commit the executor reports. A
merge commit (more than one parent) is not that task's diff, so it is rejected
with typed error `merge_commit`.

Prints JSON {status: ok|stray|skipped, stray, declared, changed}. `skipped`
when the task has no ownership fields or `kind: spike`.
Exit codes: 0 ok or skipped, 2 stray paths, 1 usage error, unreadable task,
or merge_commit.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

LIST_KEYS = ("modifies", "creates", "renames")


def unquote(value):
    return value.strip().strip("'\"").strip()


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


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def declared_paths(fm):
    paths = list(fm.get("modifies", [])) + list(fm.get("creates", []))
    for rename in fm.get("renames", []):
        parts = [p.strip() for p in rename.split("->")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"invalid rename entry: {rename}")
        paths.extend(parts)
    return sorted(set(paths))


def fail(error, message):
    print(json.dumps({"error": error, "message": message}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    task = Path(args.task).resolve()
    try:
        fm = parse_frontmatter(task)
        declared = declared_paths(fm)
    except (OSError, ValueError) as err:
        fail("unreadable_task", str(err))

    if fm.get("kind") == "spike" or not any(k in fm for k in LIST_KEYS):
        print(json.dumps({"status": "skipped", "stray": [], "declared": declared, "changed": []}))
        return 0

    try:
        parents = git(repo, "rev-list", "--parents", "-n", "1", args.commit).split()[1:]
        if len(parents) > 1:
            fail("merge_commit", f"{args.commit} has {len(parents)} parents; pass the task's own source commit")
        changed = sorted(
            git(repo, "diff-tree", "-z", "--root", "--no-commit-id", "--name-only", "--no-renames", "-r", args.commit).split("\0")
        )
    except RuntimeError as err:
        fail("git_error", str(err))

    try:
        task_rel = task.relative_to(repo).as_posix()
    except ValueError:
        task_rel = None
    changed = [p for p in changed if p and p != task_rel]
    stray = [p for p in changed if p not in declared]
    status = "stray" if stray else "ok"
    print(json.dumps({"status": status, "stray": stray, "declared": declared, "changed": changed}, indent=2))
    return 2 if stray else 0


if __name__ == "__main__":
    sys.exit(main())
