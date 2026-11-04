"""User and main merge approval routes."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_core.frontmatter import parse

from varde_runner.approvals import MergeApprovals, validate_agent_checklist
from varde_runner.user_credential import MergeApproverSecret

USER = "user"
MAX_NOTE = 500


def plan_reviewed_commit(working_dir: Path, identifier: str) -> str:
    plans = working_dir / "plans"
    for plan_file in sorted(plans.rglob("plan.md")):
        try:
            metadata, _ = parse(plan_file.read_bytes())
        except OSError, ValueError:
            continue
        if metadata.get("id", plan_file.parent.name) == identifier:
            reviewed = metadata.get("reviewed_commit")
            return reviewed if isinstance(reviewed, str) else ""
    return ""


def branch_tip(working_dir: Path, key: str) -> str | None:
    if not key.startswith("branch:"):
        return None
    branch = key.removeprefix("branch:")
    result = subprocess.run(  # noqa: S603 - fixed git argv, branch is a ref.
        [  # noqa: S607 - git is resolved from PATH.
            "git",
            "-C",
            str(working_dir),
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}^{{commit}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def create_approval_routes(
    approvals: MergeApprovals,
    secret: MergeApproverSecret | None = None,
    working_dir: Path | None = None,
) -> list[Route]:
    async def read(request: Request) -> JSONResponse:
        record = approvals.latest(request.path_params["plan_id"])
        return JSONResponse({"approval": asdict(record) if record else None})

    async def write(request: Request) -> JSONResponse:
        try:
            body = await request.json() if await request.body() else {}
        except json.JSONDecodeError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        note = body.get("note") if isinstance(body, dict) else None
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
            return JSONResponse({"error": "note must be short text"}, status_code=400)
        key = request.path_params["plan_id"]
        record = approvals.record(
            key,
            USER,
            note,
            key_kind="branch" if key.startswith("branch:") else "plan",
            commit_sha=branch_tip(working_dir, key)
            if working_dir is not None
            else None,
        )
        return JSONResponse({"approval": asdict(record)}, status_code=201)

    async def write_as_main(request: Request) -> JSONResponse:
        if secret is None or not secret.matches(
            request.headers.get("x-varde-merge-approver")
        ):
            return JSONResponse(
                {"error": "main approval secret required"}, status_code=401
            )
        try:
            body = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "JSON object required"}, status_code=400)
        checklist = body.get("checklist")
        if working_dir is None:
            return JSONResponse(
                {"error": "working directory unavailable"}, status_code=500
            )
        reviewed_commit = plan_reviewed_commit(
            working_dir, request.path_params["plan_id"]
        )
        if not reviewed_commit:
            return JSONResponse(
                {"error": "plan or reviewed_commit not found"}, status_code=404
            )
        error = validate_agent_checklist(checklist, reviewed_commit)
        if error:
            return JSONResponse({"error": error}, status_code=400)
        note = body.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
            return JSONResponse({"error": "note must be short text"}, status_code=400)
        record = approvals.record(
            request.path_params["plan_id"],
            "main",
            note,
            approver_kind="main",
            checklist=checklist,
            commit_sha=reviewed_commit,
        )
        return JSONResponse({"approval": asdict(record)}, status_code=201)

    return [
        Route("/api/plans/{plan_id:path}/merge-approval", read, methods=["GET"]),
        Route("/api/plans/{plan_id:path}/merge-approval", write, methods=["POST"]),
        Route(
            "/api/plans/{plan_id:path}/merge-approval/agent",
            write_as_main,
            methods=["POST"],
        ),
    ]
