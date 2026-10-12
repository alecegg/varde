#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
flow_file="$(mktemp "${TMPDIR:-/tmp}/plan-route-membership.XXXXXX")"
trap 'rm -f "$flow_file"' EXIT

command -v varde >/dev/null 2>&1 || { echo "FAIL: varde is required" >&2; exit 1; }
if ! varde doc flow --json "$repo_root/skills/varde-change" >"$flow_file"; then
  echo "FAIL: varde doc flow failed for varde-change" >&2
  cat "$flow_file" >&2
  exit 1
fi

python3 - "$flow_file" <<'PY'
import json
import shutil
import sys
import tempfile
from pathlib import Path


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


# The plan route loads plan.md, which links decomposition, the code CLI and the
# task template; the named-plan route decomposes; the plan-set route runs ready
# plans in dependency order. Planning no longer loads plan-path.py, which is
# deleted; worktree-create.sh belongs to the build route, not the plan route.
# Stage: (label, key file that must be the route's entry, required route files).
STAGES = (
    ("plan", "references/plan.md", (
        "references/plan.md", "references/plan-decomposition.md",
        "references/varde-code-cli.md", "assets/TASK-TEMPLATE.md")),
    ("decomposition", "references/build.md", (
        "references/plan-decomposition.md", "assets/TASK-TEMPLATE.md")),
    ("plan set", "references/orchestrate.md", (
        "references/orchestrate.md",)),
)
DELETED = ("scripts/plan-path.py",)


def files_of(route):
    return {item if isinstance(item, str) else item.get("file")
            for item in route.get("files", [])}


def varde_change_routes(flow):
    skills = flow.get("data") if isinstance(flow, dict) and flow.get("ok") is True else None
    if not isinstance(skills, list):
        return None
    matches = [item for item in skills if isinstance(item, dict)
               and item.get("skill") == "varde-change"]
    if len(matches) != 1 or not isinstance(matches[0].get("routes"), list):
        return None
    return matches[0]["routes"]


def check(flow):
    routes = varde_change_routes(flow)
    if routes is None:
        return ["flow must return one varde-change skill with routes"]
    issues = []
    for stage, key, required in STAGES:
        matched = [route for route in routes if key in route.get("entry", [])]
        if not matched:
            issues.append(f"{stage}: no route with entry {key!r}")
            continue
        for route in matched:
            present = files_of(route)
            for path in required:
                if path not in present:
                    issues.append(
                        f"{stage}: route {route['route']!r} is missing required file {path!r}")
            for path in DELETED:
                if path in present:
                    issues.append(
                        f"{stage}: route {route['route']!r} still loads deleted file {path!r}")
    return issues


def find_route(flow, key):
    return next(route for skill in flow["data"] if skill.get("skill") == "varde-change"
                for route in skill["routes"] if key in route.get("entry", []))


flow_path = Path(sys.argv[1])
try:
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"cannot read flow JSON: {exc}")
if issues := check(flow):
    fail("; ".join(issues))

# Remove a required link for each stage from a copied flow JSON.
mutations = (
    ("plan", "references/plan.md", "references/plan-decomposition.md"),
    ("decomposition", "references/build.md", "references/plan-decomposition.md"),
    ("plan set", "references/orchestrate.md", "references/orchestrate.md"),
)
with tempfile.TemporaryDirectory(prefix="plan-route-membership-") as temp_dir:
    copied = Path(temp_dir) / "flow.json"
    for stage, key, missing in mutations:
        shutil.copyfile(flow_path, copied)
        mutant = json.loads(copied.read_text(encoding="utf-8"))
        route = find_route(mutant, key)
        route["files"] = [item for item in route["files"]
                          if (item if isinstance(item, str) else item.get("file")) != missing]
        copied.write_text(json.dumps(mutant), encoding="utf-8")
        errors = check(json.loads(copied.read_text(encoding="utf-8")))
        expected = f"{stage}: route {route['route']!r} is missing required file {missing!r}"
        if expected not in errors:
            fail(f"copied-flow mutation was not rejected: {expected}")

print(f"PASS: planning route membership; rejected {len(mutations)} missing-link mutations")
PY
