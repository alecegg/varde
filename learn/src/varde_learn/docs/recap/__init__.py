"""`varde learn docs recap`: deterministic diff-to-plan mapping with drift flags."""

import json
import sys
from pathlib import Path

from varde_learn.docs.recap.build import build_recap
from varde_learn.docs.recap.gitdiff import GitError, changed_files, repo_root
from varde_learn.docs.recap.plan import read_plan


def render_text(recap: dict) -> str:
    lines = [f"recap {recap['plan']} {recap['base']}..{recap['head']}"]
    for row in recap["rows"]:
        label = ",".join(row["tasks"]) or ("shared" if row["shared"] else "-")
        flags = " ".join(row["drift"])
        lines.append(f"{row['status']} {row['file']} [{label}] {flags}".rstrip())
    lines += [f"untouched {u['task']} {u['owns']}" for u in recap["untouched"]]
    lines += [f"unverified {b}" for b in recap["unverified"]]
    summary = recap["summary"]
    lines.append(" ".join(f"{k}={v}" for k, v in summary.items()))
    return "\n".join(lines) + "\n"


def run(plan_file: Path, base: str, head: str, json_output: bool) -> int:
    if not plan_file.is_file():
        print(f"error: plan file not found: {plan_file}", file=sys.stderr)
        return 1
    try:
        root = repo_root(Path.cwd())
        changes = changed_files(root, base, head)
        plan = read_plan(plan_file)
    except (GitError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    recap = build_recap(plan, changes, base, head, plan_file.parent.name)
    if json_output:
        print(json.dumps(recap, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_text(recap), end="")
    return 0
