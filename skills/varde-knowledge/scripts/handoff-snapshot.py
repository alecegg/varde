#!/usr/bin/env python3
"""Print handoff snapshot entries (path, hash) for files or directories.

Usage: handoff-snapshot.py -- <target>...
See references/handoff-snapshot.md.
"""
import hashlib
import json
import os
import subprocess
import sys


def in_git(location):
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=location, capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def file_hash(path, use_git, location):
    if use_git:
        result = subprocess.run(
            ["git", "hash-object", "--no-filters", "--", os.path.abspath(path)],
            cwd=location, capture_output=True, text=True, check=True,
        )
        return "git-blob:" + result.stdout.strip()
    with open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def snapshot(target, skipped):
    if os.path.islink(target):
        skipped.append(target)
        return []
    is_dir = os.path.isdir(target)
    location = target if is_dir else os.path.dirname(os.path.abspath(target))
    use_git = in_git(location)
    if not is_dir:
        return [{"path": ".", "hash": file_hash(target, use_git, location)}]
    entries = []
    for root, dirs, files in os.walk(target):
        for name in list(dirs):
            full = os.path.join(root, name)
            if os.path.islink(full):
                dirs.remove(name)
                skipped.append(full)
        for name in files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                skipped.append(full)
                continue
            rel = os.path.relpath(full, target)
            entries.append({"path": rel, "hash": file_hash(full, use_git, location)})
    return sorted(entries, key=lambda entry: entry["path"].encode())


def main(argv):
    if len(argv) < 2 or argv[0] != "--":
        print("usage: handoff-snapshot.py -- <target>...", file=sys.stderr)
        return 2
    skipped = []
    snapshots = {}
    for target in argv[1:]:
        if not os.path.lexists(target):
            print(f"missing target: {target}", file=sys.stderr)
            return 1
        snapshots[target] = snapshot(target, skipped)
    print(json.dumps({"snapshots": snapshots, "skipped_symlinks": sorted(skipped)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
