#!/usr/bin/env bash
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
source "$REPO_ROOT/workflow/tests/lib/varde-bin.sh"
prefer_checkout_varde "$REPO_ROOT"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
flow_file="$(mktemp "${TMPDIR:-/tmp}/status-verify-boundary.XXXXXX")"
trap 'rm -f "$flow_file"' EXIT

command -v varde >/dev/null 2>&1 || { echo "FAIL: varde is required" >&2; exit 1; }
if ! varde learn measure "$(skill_dir varde-plan)" flow --json "$(skill_dir varde-build)" "$(skill_dir varde-orchestrate)" "$(skill_dir varde-swarm)" >"$flow_file"; then
  echo "FAIL: varde learn measure <skill> flow failed for tier skills" >&2
  cat "$flow_file" >&2
  exit 1
fi

python3 - "$flow_file" <<'PY'
import json
import sys
from pathlib import Path


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def file_names(items):
    names = set()
    for item in items:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and isinstance(item.get("file"), str):
            names.add(item["file"])
        else:
            return None
    return names


def check(flow):
    skills = flow.get("data") if isinstance(flow, dict) and flow.get("ok") is True else None
    if not isinstance(skills, list):
        return ["flow must return ok=true with a data list"]
    by_name = {item.get("skill"): item for item in skills if isinstance(item, dict)}
    expected = {
        "varde-swarm": ("Current work or empty invocation", "references/status.md"),
        "varde-build": ("Verify completed work without changes", "references/verify.md"),
    }
    forbidden = ("review-gate", "conform.md", "worktree")
    issues = []
    for skill, (label, required) in expected.items():
        matches = by_name.get(skill, {}).get("routes", [])
        routes = [r for r in matches if r.get("route") == label]
        if len(routes) != 1:
            issues.append(f"{skill}: expected one {label} route")
            continue
        route = routes[0]
        files = route.get("files")
        min_files = route.get("min_files")
        dispatches = route.get("dispatches")
        if not isinstance(files, list) or not isinstance(min_files, list) or not isinstance(dispatches, list):
            issues.append(f"{skill}: route files, min_files, and dispatches must be lists")
            continue
        if required not in files or required not in min_files:
            issues.append(f"{skill}: {label} route must load {required!r} unconditionally")
        names = file_names(min_files)
        if names is None:
            issues.append(f"{skill}: {label} min_files entries must be paths or file objects")
            continue
        if any(any(term in file.lower() for term in forbidden) for file in names):
            issues.append(f"{skill}: {label} route unconditionally loads forbidden review/worktree files")
        for dispatch in dispatches:
            if not isinstance(dispatch, dict):
                issues.append(f"{skill}: {label} dispatch must be an object")
            elif (
                (isinstance(dispatch.get("agent"), str) and dispatch["agent"].casefold() == "review"
                 or isinstance(dispatch.get("runs"), str)
                 and ("review gate" in dispatch["runs"].casefold() or "varde-review:" in dispatch["runs"].casefold()))
                and dispatch.get("conditional") is not True
            ):
                issues.append(f"{skill}: {label} route has an unconditional reviewer dispatch")
    return issues

flow_path = Path(sys.argv[1])
try:
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"cannot read flow JSON: {exc}")
if issues := check(flow):
    fail("; ".join(issues))

print("PASS: Status/Verify active route boundary")
PY
