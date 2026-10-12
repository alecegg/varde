#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
flow_file="$(mktemp "${TMPDIR:-/tmp}/status-verify-boundary.XXXXXX")"
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


# `files` includes conditional resources. On these read-only routes, min_files
# is the always-loaded path; conditional review dispatches are not active.
ROUTES = (
    ('"What', "Status", "references/status.md"),
    ("Report evidence for finished work", "Verify", "references/verify.md"),
)


def names(items):
    return {item if isinstance(item, str) else item.get("file")
            for item in items if isinstance(item, str) or isinstance(item, dict)}


def route_for(flow, prefix, issues):
    skills = flow.get("data") if isinstance(flow, dict) and flow.get("ok") is True else None
    if not isinstance(skills, list):
        issues.append("flow must return ok=true with a data list")
        return None
    skills = [item for item in skills if isinstance(item, dict) and item.get("skill") == "varde-change"]
    if len(skills) != 1 or not isinstance(skills[0].get("routes"), list):
        issues.append("expected one varde-change skill with routes")
        return None
    matches = [item for item in skills[0]["routes"] if isinstance(item, dict)
               and isinstance(item.get("route"), str) and item["route"].startswith(prefix)]
    if len(matches) != 1:
        issues.append(f"expected one route starting {prefix!r}, found {len(matches)}")
        return None
    return matches[0]


def forbidden(path):
    path = path.casefold()
    filename = path.rsplit("/", 1)[-1]
    return (filename.startswith("review-gate") and filename.endswith(".md")) or "worktree" in path


def review_dispatch(dispatch):
    agent, runs = dispatch.get("agent", ""), dispatch.get("runs", "")
    return (isinstance(agent, str) and agent.casefold() == "review") or (
        isinstance(runs, str) and ("review gate" in runs.casefold() or "varde-review:" in runs.casefold())
    )


def check(flow):
    issues = []
    for prefix, label, required in ROUTES:
        route = route_for(flow, prefix, issues)
        if route is None:
            continue
        always = route.get("min_files")
        dispatches = route.get("dispatches")
        if not isinstance(always, list) or not isinstance(dispatches, list):
            issues.append(f"{label}: min_files and dispatches must be lists")
            continue
        always = names(always)
        if required not in always:
            issues.append(f"{label}: always-loaded route is missing {required!r}")
        for path in always:
            if isinstance(path, str) and forbidden(path):
                issues.append(f"{label}: forbidden always-loaded file {path!r}")
        for dispatch in dispatches:
            if not isinstance(dispatch, dict):
                issues.append(f"{label}: dispatch must be an object")
            elif review_dispatch(dispatch) and dispatch.get("conditional") is not True:
                issues.append(f"{label}: active review dispatch {dispatch.get('runs')!r}")
    return issues


def find_route(flow, prefix):
    return next(route for skill in flow["data"] if skill.get("skill") == "varde-change"
                for route in skill["routes"] if route["route"].startswith(prefix))


flow_path = Path(sys.argv[1])
try:
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"cannot read flow JSON: {exc}")
if issues := check(flow):
    fail("; ".join(issues))


def mutation_fails(mutate, expected):
    with tempfile.TemporaryDirectory(prefix="status-verify-boundary-") as temp_dir:
        copied = Path(temp_dir) / "flow.json"
        shutil.copyfile(flow_path, copied)
        mutant = json.loads(copied.read_text(encoding="utf-8"))
        mutate(mutant)
        copied.write_text(json.dumps(mutant), encoding="utf-8")
        if expected not in check(json.loads(copied.read_text(encoding="utf-8"))):
            fail(f"copied-flow mutation was not rejected: {expected}")


mutations = 0
for prefix, label, _required in ROUTES:
    def add_review(data, prefix=prefix):
        find_route(data, prefix)["dispatches"].append(
            {"agent": "review", "conditional": False, "runs": "review gate"}
        )

    expected = f"{label}: active review dispatch 'review gate'"
    mutation_fails(add_review, expected)
    mutations += 1
    for path in ("references/review-gate-plan.md", "references/build-worktree.md"):
        def add_file(data, prefix=prefix, path=path):
            route = find_route(data, prefix)
            route["min_files"].append(path)

        mutation_fails(add_file, f"{label}: forbidden always-loaded file {path!r}")
        mutations += 1

print(f"PASS: Status/Verify active route boundary; rejected {mutations} review-dispatch and forbidden-file mutations")
PY
