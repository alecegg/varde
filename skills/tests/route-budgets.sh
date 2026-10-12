#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
fixture="$script_dir/fixtures/route-budgets.json"
mode=self-test
flow_file=""
tmp_dir=""

if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
elif [[ $# -eq 1 ]]; then
  if [[ "$1" != "--check" ]]; then
    echo "Usage: $0 [--check]" >&2
    exit 2
  fi
  mode=check
fi

if [[ "$mode" == check ]]; then
  if ! command -v varde >/dev/null 2>&1; then
    echo "FAIL: varde is required for route budget checks" >&2
    exit 1
  fi

  skill_dirs=()
  for skill_dir in "$repo_root"/skills/varde-*; do
    if [[ -f "$skill_dir/SKILL.md" ]]; then
      skill_dirs+=("$skill_dir")
    fi
  done
  if [[ ${#skill_dirs[@]} -eq 0 ]]; then
    echo "FAIL: no Varde skill directories found under $repo_root/skills" >&2
    exit 1
  fi

  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/route-budgets.XXXXXX")"
  trap 'rm -rf "$tmp_dir"' EXIT
  flow_file="$tmp_dir/flow.json"
  if ! varde doc flow --json "${skill_dirs[@]}" > "$flow_file"; then
    echo "FAIL: varde doc flow failed for the Varde skills" >&2
    cat "$flow_file" >&2
    exit 1
  fi
fi

python3 - "$mode" "$flow_file" "$fixture" <<'PY'
import json
import sys
import tempfile
from pathlib import Path

mode, flow_path, fixture_path = sys.argv[1:]
PROTECTED = {
    "varde-change": {
        "build": ("named plan",),
        "orchestrate": ("plan set",),
        "builder": ("task file", "orchestrator"),
    },
    "varde-review": {"report": ("diff", "branch", "code area")},
}


def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def protected_kind(entry):
    skill = entry["skill"]
    route = entry["route"].casefold()
    for kind, markers in PROTECTED.get(skill, {}).items():
        if all(marker in route for marker in markers):
            return kind
    return None


def is_protected(entry):
    return protected_kind(entry) is not None


def read_fixture(filename):
    try:
        entries = json.loads(Path(filename).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read fixture {filename}: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError("fixture must be a JSON array of route budgets")
    return entries


def route_data(flow):
    if not isinstance(flow, dict) or flow.get("ok") is not True:
        error = flow.get("data", {}).get("error") if isinstance(flow, dict) else None
        raise ValueError(f"varde doc flow did not return ok=true: {error or flow!r}")
    skills = flow.get("data")
    if not isinstance(skills, list):
        raise ValueError("varde doc flow data must be a list")

    routes = {}
    skills_with_routes = set()
    skill_names = set()
    for skill_data in skills:
        if not isinstance(skill_data, dict) or not isinstance(skill_data.get("skill"), str):
            raise ValueError("flow data contains a skill without a name")
        skill = skill_data["skill"]
        if skill in skill_names:
            raise ValueError(f"flow data repeats skill {skill!r}")
        skill_names.add(skill)
        items = skill_data.get("routes")
        if not isinstance(items, list):
            raise ValueError(f"flow routes for {skill} must be a list")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("route"), str):
                raise ValueError(f"flow contains a route without a name for {skill}")
            key = (skill, item["route"])
            if key in routes:
                raise ValueError(f"flow repeats route {skill} / {item['route']}")
            metrics = (item.get("main_min_tokens"), item.get("main_max_tokens"))
            if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in metrics):
                raise ValueError(f"flow has invalid main token counts for {skill} / {item['route']}")
            routes[key] = metrics
            skills_with_routes.add(skill)
    if not skill_names:
        raise ValueError("varde doc flow returned no skills")
    return routes, skill_names, skills_with_routes


def evaluate(entries, flow):
    issues = []
    route_metrics, flow_skills, skills_with_routes = route_data(flow)
    budgets = {}
    allowed_fields = {"skill", "route", "typical", "max", "set_by", "waived", "approved_by_user"}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            issues.append(f"fixture row {index} must be an object")
            continue
        extra = set(entry) - allowed_fields
        missing_fields = {"skill", "route", "typical", "max", "set_by"} - set(entry)
        if extra:
            issues.append(f"fixture row {index} has unknown fields: {', '.join(sorted(extra))}")
        if missing_fields:
            issues.append(f"fixture row {index} is missing fields: {', '.join(sorted(missing_fields))}")
            continue
        if not isinstance(entry["skill"], str) or not isinstance(entry["route"], str):
            issues.append(f"fixture row {index} must name a skill and route")
            continue
        if entry["set_by"] not in ("user", "proposal"):
            issues.append(f"{entry['skill']} / {entry['route']}: set_by must be user or proposal")
        values = (entry["typical"], entry["max"])
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            issues.append(f"{entry['skill']} / {entry['route']}: typical and max must be nonnegative integers")
            continue
        key = (entry["skill"], entry["route"])
        if key in budgets:
            issues.append(f"fixture repeats route {key[0]} / {key[1]}")
        budgets[key] = entry

    expected = set(route_metrics)
    actual = set(budgets)
    for skill, route in sorted(expected - actual):
        issues.append(f"missing budget for {skill} / {route}")
    for skill, route in sorted(actual - expected):
        issues.append(f"budget has no matching flow route: {skill} / {route}")
    if issues:
        return issues, {"skills": len(flow_skills), "routes": len(route_metrics), "misses": 0, "waived": 0, "unbudgeted_skills": sorted(skills_with_routes - {s for s, _ in budgets})}

    misses = 0
    waived = 0
    for key, entry in sorted(budgets.items()):
        measured_min, measured_max = route_metrics[key]
        reasons = []
        if measured_min > entry["typical"]:
            reasons.append(f"main_min {measured_min} > typical {entry['typical']}")
        if measured_max > entry["max"]:
            reasons.append(f"main_max {measured_max} > max {entry['max']}")
        has_waiver = "waived" in entry
        waiver = entry.get("waived")
        valid_waiver = isinstance(waiver, str) and bool(waiver.strip())
        if has_waiver and not valid_waiver:
            issues.append(f"{key[0]} / {key[1]}: waived must contain a reason")
        if has_waiver and is_protected(entry):
            approval = entry.get("approved_by_user")
            approved = approval is True or (isinstance(approval, str) and bool(approval.strip()))
            if not approved:
                issues.append(f"{key[0]} / {key[1]}: waiver requires approved_by_user")
                valid_waiver = False
        if reasons:
            misses += 1
            if has_waiver and valid_waiver:
                waived += 1
            else:
                issues.append(f"{key[0]} / {key[1]}: {'; '.join(reasons)} (unwaived)")
    return issues, {"skills": len(flow_skills), "routes": len(route_metrics), "misses": misses, "waived": waived, "unbudgeted_skills": sorted(skills_with_routes - {s for s, _ in budgets})}


def self_test(entries):
    protected_entries = [entry for entry in entries if isinstance(entry, dict) and is_protected(entry)]
    expected = {("varde-change", "build"), ("varde-change", "orchestrate"), ("varde-change", "builder"), ("varde-review", "report")}
    found = {(entry["skill"], protected_kind(entry)) for entry in protected_entries}
    if found != expected:
        raise ValueError(f"fixture protected routes mismatch: expected {sorted(expected)}, got {sorted(found)}")

    for protected_entry in protected_entries:
        row = {
            "skill": protected_entry["skill"],
            "route": protected_entry["route"],
            "typical": 10,
            "max": 10,
            "set_by": "user",
        }
        flow = {"ok": True, "data": [{"skill": row["skill"], "routes": [{"route": row["route"], "main_min_tokens": 10, "main_max_tokens": 10}]}]}
        issues, _ = evaluate([row], flow)
        if issues:
            raise ValueError(f"within-budget fixture should pass for {protected_kind(row)}: {issues}")

        over_budget_flow = {"ok": True, "data": [{"skill": row["skill"], "routes": [{"route": row["route"], "main_min_tokens": 10, "main_max_tokens": 11}]}]}
        issues, _ = evaluate([row], over_budget_flow)
        if not any("unwaived" in issue for issue in issues):
            raise ValueError(f"unwaived over-budget fixture was not rejected for {protected_kind(row)}: {issues}")

        unapproved = dict(row, waived="self-test waiver without user approval")
        with tempfile.TemporaryDirectory(prefix="route-budgets-self-test-") as temporary:
            unapproved_fixture = Path(temporary) / "unapproved-user-route-waiver.json"
            unapproved_fixture.write_text(json.dumps([unapproved]), encoding="utf-8")
            fixture_rows = read_fixture(unapproved_fixture)
            issues, _ = evaluate(fixture_rows, over_budget_flow)
        if not any("requires approved_by_user" in issue for issue in issues):
            raise ValueError(f"unapproved {protected_kind(row)} waiver fixture was not refused: {issues}")

        approved = dict(unapproved, approved_by_user="self-test user approval")
        issues, _ = evaluate([approved], over_budget_flow)
        if issues:
            raise ValueError(f"approved {protected_kind(row)} waiver should pass: {issues}")


try:
    entries = read_fixture(fixture_path)
    if mode == "self-test":
        self_test(entries)
        print("PASS: route budget self-test (coverage, budget misses, and unapproved user-route waiver refusal)")
        raise SystemExit(0)
    flow = json.loads(Path(flow_path).read_text(encoding="utf-8"))
    issues, stats = evaluate(entries, flow)
except (OSError, json.JSONDecodeError, ValueError) as exc:
    fail(str(exc))

for issue in issues:
    print(f"FAIL: {issue}", file=sys.stderr)
if issues:
    fail(f"{stats['routes']} routes across {stats['skills']} skills; {stats['misses']} over budget, {stats['waived']} waived")

print(f"PASS: {stats['routes']} routes across {stats['skills']} skills; {stats['misses']} over budget, {stats['waived']} waived")
if stats["unbudgeted_skills"]:
    print("Skills with no measured routes: " + ", ".join(stats["unbudgeted_skills"]))
PY
