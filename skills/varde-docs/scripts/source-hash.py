#!/usr/bin/env python3
"""Print the spec source_hash for the given paths.

Run from the repository root: source-hash.py -- <path>...
"""
import os
import subprocess
import sys


def git_hash(args, data=None):
    result = subprocess.run(
        ["git", "hash-object", *args], input=data, capture_output=True
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode(errors="replace"))
        sys.exit(1)
    return result.stdout.strip()


def main(argv):
    paths = argv[1:]
    if paths[:1] == ["--"]:
        paths = paths[1:]
    if not paths:
        sys.stderr.write("usage: source-hash.py -- <path>...\n")
        return 2
    joined = b"".join(
        path + git_hash(["--no-filters", "--", os.fsdecode(path)])
        for path in sorted(os.fsencode(p) for p in paths)
    )
    sys.stdout.write(git_hash(["--stdin"], joined).decode() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
