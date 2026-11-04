"""Read dependency readiness for one workflow artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from varde_workflow.errors import InternalError, report_error
from varde_workflow.graph import ArtifactGraph
from varde_workflow.output import print_cli_success
from varde_workflow.plan_comments import open_comment_count
from varde_workflow.plan_overlap import plan_overlaps, sibling_plan_dirs
from varde_workflow.schema import WorkflowSchema


def readiness_data(path: str) -> dict[str, Any]:
    schema = WorkflowSchema.resolve(path)
    graph = ArtifactGraph.resolve(path, schema)
    readiness = graph.readiness_json(schema)
    ready = readiness.get("ready") is True
    readiness["planning_ready"] = ready
    readiness["implementation_ready"] = ready
    plan_path = Path(path)
    readiness["open_comments"] = open_comment_count(plan_path)
    warnings = []
    if plan_path.name == "plan.md":
        warnings = plan_overlaps(plan_path.parent, sibling_plan_dirs(plan_path))
    readiness["overlap_warnings"] = warnings
    return readiness


def run(args: Any) -> int:
    try:
        data = readiness_data(args.plan)
    except Exception as exc:
        return report_error(InternalError(str(exc)), args.json)
    if args.json:
        print_cli_success(data)
    else:
        for warning in data["overlap_warnings"]:
            files = warning["files"]
            shown = files[:5]
            more = len(files) - len(shown)
            suffix = f", and {more} more" if more else ""
            print(f"warning: overlaps {warning['plan']} on {', '.join(shown)}{suffix}")
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
