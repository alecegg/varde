"""Record main's checked merge approval through the runner's secret endpoint."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

from varde_core.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.error import CliError, report_cli_error
from varde_workflow.commands.owner import resolve_plan
from varde_workflow.merge_approval import runner_port


def checklist_for(
    plan: Path,
    metadata: dict[str, Any],
    *,
    plan_followed: bool,
    gate_result: str,
    abnormal_events: str,
) -> dict[str, object]:
    reviewed = metadata.get("reviewed_commit")
    if not isinstance(reviewed, str) or not reviewed.strip():
        raise ValueError("plan has no reviewed_commit")
    review_file = plan.parent / "review.md"
    review = review_file.read_text(encoding="utf-8") if review_file.is_file() else ""
    verdict = next(
        (
            line.partition(":")[2].strip().lower()
            for line in review.splitlines()
            if line.strip().lower().startswith("verdict:")
        ),
        "",
    )
    if verdict not in {"pass", "passed", "approve", "approved"}:
        raise ValueError("review.md must contain a passing verdict")
    if gate_result.strip().lower() not in {"pass", "passed"}:
        raise ValueError("gate result must be pass")
    if not plan_followed:
        raise ValueError("--plan-followed is required")
    if not abnormal_events.strip():
        raise ValueError("--abnormal-events must be non-empty")
    return {
        "plan_followed": plan_followed,
        "review_commit": reviewed,
        "gate_result": gate_result,
        "abnormal_events": abnormal_events,
    }


def run(args: Any) -> int:
    try:
        cwd = Path.cwd()
        working = MemoryPaths.resolve(cwd).working.path
        plan = resolve_plan(args.plan, cwd, working / "plans")
        metadata, _ = parse(plan.read_bytes())
        identifier = metadata.get("id", plan.parent.name)
        checklist = checklist_for(
            plan,
            metadata,
            plan_followed=args.plan_followed,
            gate_result=args.gate_result,
            abnormal_events=args.abnormal_events,
        )
        state = Path(
            os.environ.get(
                "VARDE_RUNNER_STATE_DIR", Path.home() / ".local/share/varde-runner"
            )
        )
        secret = (state / "merge-approver-main").read_text(encoding="utf-8").strip()
        payload = json.dumps({"note": args.note, "checklist": checklist}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{runner_port(os.environ)}"
            f"/api/plans/{quote(str(identifier), safe='')}/merge-approval/agent",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Varde-Merge-Approver": secret,
            },
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            result = json.load(response)
        print(json.dumps(result["approval"], indent=2, sort_keys=True))
        print(
            "Checklist source: reviewed_commit from plan.md and explicit CLI options."
        )
    except (OSError, ValueError, KeyError, urllib.error.URLError, CliError) as exc:
        return report_cli_error(CliError(str(exc)), json=getattr(args, "json", False))
    return 0
