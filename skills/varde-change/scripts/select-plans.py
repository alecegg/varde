#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List the plans `varde-change` build can select.

Usage: select-plans.py --working DIR

Reads every `plan.md` at any depth under DIR/plans. Skips `shape: group` plans
and drafts (id ending `-draft`, or a live bullet under `## Open Questions`).
Keeps `backlog` and `active` plans. With `varde-workflow` on PATH it runs
`readiness <plan> --json` per plan and `graph <plan> --json --all` per
candidate (graph covers one plan's `depends_on` closure, so every candidate is
checked), excludes plans with an incomplete dependency or named by a
`dependency_cycle` blocker, and orders backlog first, then by id.

Output (stdout, exit 0):
  {plans: [{id, title, status, implementation_ready, blockers: [...]}],
   excluded_by_dependency: N, cycles: [ids], degraded: bool,
   degraded_plans: [ids]}

`degraded` is true when `varde-workflow` is missing or a call failed;
`degraded_plans` lists the affected ids. Those plans are filtered by their
`depends_on` front matter instead: any dependency not `completed` excludes
the plan. Failure prints {"error", "message"} and
exits 1 (usage or unreadable working directory).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def fail(name, message):
    print(json.dumps({"error": name, "message": message}))
    sys.exit(1)


def parse_list(value, following):
    """Parse an inline `[a, b]` or block `- a` YAML list of ids."""
    value = value.strip()
    if value.startswith("["):
        items = value.strip("[]").split(",")
    else:
        items = []
        for line in following:
            if not re.match(r"\s*-\s", line) and line.strip():
                break
            if line.strip():
                items.append(line.strip()[1:])
    return [i.strip().strip("\"'") for i in items if i.strip().strip("\"'")]


def read_plan(path):
    """Return (id, title, status, shape, has_open_question, depends_on) or None."""
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if not match:
        return None
    front = {}
    depends = []
    lines = match.group(1).splitlines()
    for number, line in enumerate(lines):
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "-")):
            front[key.strip()] = value.strip().strip("\"'")
            if key.strip() == "depends_on":
                depends = parse_list(value, lines[number + 1:])
    body = text[match.end():]
    live = False
    section = re.search(r"^## Open Questions\s*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    if section:
        live = bool(re.search(r"^\s*(?:[-*]|\d+\.)\s+\S", section.group(1), re.M))
    return (front.get("id") or path.parent.name, front.get("title", ""),
            front.get("status", ""), front.get("shape", ""), live, depends)


def dependency_status(path, statuses):
    """Status of a dependency plan.md, reading it when outside the scanned plans."""
    path = path.resolve()
    if path not in statuses:
        try:
            info = read_plan(path) if path.is_file() else None
        except OSError:
            info = None
        statuses[path] = info[2] if info else None
    return statuses[path]


def workflow(args):
    """Return the `data` object of a varde-workflow JSON call, or None."""
    try:
        done = subprocess.run(["varde-workflow", *args, "--json"], capture_output=True,
                              text=True, timeout=60)
        if done.returncode != 0:
            return None
        return json.loads(done.stdout)["data"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", required=True)
    args = parser.parse_args()
    plans_dir = Path(args.working) / "plans"
    if not plans_dir.is_dir():
        fail("working_missing", f"no plans directory at {plans_dir}")

    candidates = []
    statuses = {}
    for path in sorted(plans_dir.rglob("plan.md")):
        info = read_plan(path)
        if not info:
            continue
        plan_id, title, status, shape, live, depends = info
        statuses[path.resolve()] = status
        if shape == "group" or plan_id.endswith("-draft") or live:
            continue
        if status in ("backlog", "active"):
            candidates.append({"id": plan_id, "title": title, "status": status,
                               "path": path, "depends": depends})

    have_cli = shutil.which("varde-workflow") is not None
    degraded_plans = set() if have_cli else {c["id"] for c in candidates}
    cycles = []
    excluded = 0
    plans = []
    if have_cli:
        for plan in candidates:
            graph = workflow(["graph", str(plan["path"]), "--all"])
            if graph is None:
                degraded_plans.add(plan["id"])
                continue
            for blocker in graph["blockers"]:
                if blocker.get("code") == "dependency_cycle":
                    for name in (blocker.get("artifact_id"), blocker.get("dependency")):
                        if name and name not in cycles:
                            cycles.append(name)
    for plan in candidates:
        ready, blockers = False, []
        data = None
        if plan["id"] not in degraded_plans:
            data = workflow(["readiness", str(plan["path"])])
            if data is None:
                degraded_plans.add(plan["id"])
        if data is None:
            # Resolve like varde-workflow: <plan_dir>/../<dep>/plan.md, no id fallback.
            plan_dir = plan["path"].parent
            if any(dependency_status(plan_dir.parent / d / "plan.md", statuses) != "completed"
                   for d in plan["depends"]):
                excluded += 1
                continue
        else:
            blockers = list(data["blockers"])
            blockers += (data.get("review") or {}).get("blockers", [])
            ready = bool(data["implementation_ready"])
            if not data["planning_ready"] or plan["id"] in cycles:
                excluded += 1
                continue
        plans.append({"id": plan["id"], "title": plan["title"], "status": plan["status"],
                      "implementation_ready": ready, "blockers": blockers})
    plans.sort(key=lambda p: (p["status"] != "backlog", p["id"]))
    print(json.dumps({"plans": plans, "excluded_by_dependency": excluded,
                      "cycles": sorted(cycles), "degraded": bool(degraded_plans),
                      "degraded_plans": sorted(degraded_plans)}, indent=2))


if __name__ == "__main__":
    main()
