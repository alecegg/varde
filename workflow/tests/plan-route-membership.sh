#!/usr/bin/env bash
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
source "$REPO_ROOT/workflow/tests/lib/varde-bin.sh"
prefer_checkout_varde "$REPO_ROOT"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
flow_file="$(mktemp "${TMPDIR:-/tmp}/plan-route-membership.XXXXXX")"
trap 'rm -f "$flow_file"' EXIT

command -v varde >/dev/null 2>&1 || { echo "FAIL: varde is required" >&2; exit 1; }
if ! varde learn measure "$(skill_dir varde-plan)" flow --json "$(skill_dir varde-build)" "$(skill_dir varde-orchestrate)" "$(skill_dir varde-swarm)" "$(skill_dir varde-review)" >"$flow_file"; then
  echo "FAIL: varde learn measure <skill> flow failed for tier skills or varde-review" >&2
  cat "$flow_file" >&2
  exit 1
fi

python3 - "$flow_file" "$repo_root" <<'PY'
import json
import sys
from pathlib import Path


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def files_by_skill(flow):
    skills = flow.get("data") if isinstance(flow, dict) and flow.get("ok") is True else None
    if not isinstance(skills, list):
        return None
    return {item.get("skill"): item for item in skills if isinstance(item, dict)}


def check(flow):
    skills = files_by_skill(flow)
    if skills is None:
        return ["flow must return an ok data list"]
    issues = []
    stages = (
        ("varde-plan", "Settle scope before implementation", "references/plan.md",
         ("references/plan.md", "references/plan-decomposition.md", "references/varde-code-cli.md", "assets/PLAN-TEMPLATE.md", "references/TASK-TEMPLATE.md")),
        ("varde-build", "Settled standalone change", "references/build-micro-change.md",
         ("references/build-micro-change.md", "references/TASK-TEMPLATE.md", "references/build-execution.md", "references/review-gates.md")),
        ("varde-orchestrate", "Coordinate one plan", "references/build-finish.md",
         ("references/build-finish.md", "references/review-gates.md")),
        ("varde-swarm", "Run a selected plan set", "references/orchestrate.md",
         ("references/orchestrate.md", "references/main-agent.md")),
    )
    for skill, label, entry, required in stages:
        routes = [r for r in skills.get(skill, {}).get("routes", []) if r.get("route") == label]
        if len(routes) != 1:
            issues.append(f"{skill}: expected one {label!r} route")
            continue
        route = routes[0]
        present = set(route.get("files", []))
        if entry not in route.get("entry", []):
            issues.append(f"{skill}: {label} entry must include {entry!r}")
        for path in required:
            if path not in present:
                issues.append(f"{skill}: {label} route is missing {path!r}")
        if "scripts/plan-path.py" in present:
            issues.append(f"{skill}: deleted plan-path.py must not load")
    build_skill = Path(sys.argv[2]) / "workflow/src/varde_workflow/skills/varde-build/SKILL.md"
    build_text = build_skill.read_text(encoding="utf-8")
    if "Read `references/build-execution.md` and `references/review-gates.md`." not in build_text:
        issues.append("varde-build: execution and review references must be shared by every route")
    plan_routes = skills.get("varde-plan", {}).get("routes", [])
    if not any("references/plan-decomposition.md" in r.get("entry", []) for r in plan_routes):
        issues.append("varde-plan: decomposition stage must enter at plan-decomposition.md")
    if (Path(sys.argv[2]) / "workflow/src/varde_workflow/skills/varde-plan/scripts/plan-path.py").exists():
        issues.append("varde-plan: deleted plan-path.py must remain absent")
    review = skills.get("varde-review", {}).get("routes", [])
    conform = [r for r in review if r.get("route") == "Check a plan against its tasks and criteria"]
    if len(conform) != 1 or "references/conform.md" not in conform[0].get("files", []):
        issues.append("varde-review conformance route must load references/conform.md")
    return issues

flow_path = Path(sys.argv[1])
try:
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"cannot read flow JSON: {exc}")
if issues := check(flow):
    fail("; ".join(issues))

print("PASS: tier route membership")
PY
