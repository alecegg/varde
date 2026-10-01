#!/usr/bin/env python3
"""Allocate and finalize plan directory paths.

  plan-path.py draft --working <dir> --slug <slug>
  plan-path.py finalize --draft <plan-dir> --slug <slug>

draft creates <working>/plans/<UTC-date>-<slug>-draft[-N]/ and prints it.
finalize renames a draft to <draft-date>-<slug> and prints the new path and
`ignored: true|false`. Ignored plans and plans outside a repo use a plain
move; tracked drafts use `git mv`. An existing destination is refused.
"""
import argparse
import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def draft(working, slug):
    plans = Path(working) / "plans"
    base = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d}-{slug}-draft"
    target, n = plans / base, 1
    while target.exists():
        n += 1
        target = plans / f"{base}-{n}"
    target.mkdir(parents=True)
    print(target)


def finalize(draft_dir, slug):
    src = Path(draft_dir).absolute()
    date = re.match(r"\d{4}-\d{2}-\d{2}", src.name)
    if not date:
        sys.exit(f"draft name has no leading date: {src.name}")
    dest = src.parent / f"{date.group()}-{slug}"
    if dest.exists():
        sys.exit(f"destination exists: {dest}")
    in_repo = git(src, "rev-parse", "--is-inside-work-tree").returncode == 0
    ignored = not in_repo or git(src, "check-ignore", "-q", str(dest / "plan.md")).returncode == 0
    tracked = in_repo and not ignored and bool(git(src, "ls-files", str(src)).stdout.strip())
    if tracked:
        moved = git(src.parent, "mv", str(src), str(dest))
        if moved.returncode:
            sys.exit(moved.stderr.strip())
    else:
        shutil.move(str(src), str(dest))
    print(dest)
    print(f"ignored: {str(ignored).lower()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--working", required=True)
    d.add_argument("--slug", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--draft", required=True)
    f.add_argument("--slug", required=True)
    args = parser.parse_args()
    if args.command == "draft":
        draft(args.working, args.slug)
    else:
        finalize(args.draft, args.slug)


if __name__ == "__main__":
    main()
