"""HTTP routes for built-in scheduled jobs."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.job_control import (
    review_run_fields,
    soak_run_fields,
    sweep_run_fields,
)
from varde_runner.job_registry import BUILTIN_JOBS, JOBS_BY_KEY, JobSpec
from varde_runner.job_store import (
    finish_run,
    get_budget,
    get_enabled,
    recent_runs,
    set_budget,
    set_enabled,
    start_run,
)

logger = logging.getLogger(__name__)


class JobsController:
    def __init__(self, connection: sqlite3.Connection, jobs: dict[str, Any]) -> None:
        self.connection = connection
        self.jobs = jobs
        self.manual_runs: dict[str, asyncio.Task[Any]] = {}

    def is_running(self, key: str) -> bool:
        task = self.manual_runs.get(key)
        if task is not None and not task.done():
            return True
        runs = recent_runs(self.connection, key, 1)
        return bool(runs) and runs[0]["outcome"] == "running"

    async def run_in_background(self, key: str) -> None:
        if self.is_running(key):
            return
        task = asyncio.create_task(self.jobs[key].run_now())
        self.manual_runs[key] = task
        task.add_done_callback(lambda done: self._manual_run_done(key, done))
        await asyncio.sleep(0)

    def _manual_run_done(self, key: str, task: asyncio.Task[Any]) -> None:
        self.manual_runs.pop(key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("manual job run failed: %r", error)

    def enabled(self, spec: JobSpec) -> bool:
        return get_enabled(self.connection, spec)

    def start(self, key: str, trigger: str) -> int:
        return start_run(self.connection, key, trigger)

    def finish(
        self,
        key: str,
        run_id: int,
        snapshot: dict[str, Any],
        error: BaseException | None,
    ) -> None:
        if error is not None:
            finish_run(
                self.connection, run_id, outcome="failed", error=str(error)[:500]
            )
            return
        projector = {"sweep": sweep_run_fields, "review": review_run_fields}.get(
            key, soak_run_fields
        )
        fields = projector(snapshot)
        finish_run(self.connection, run_id, **fields)

    def job(self, key: str) -> dict[str, Any]:
        spec = JOBS_BY_KEY[key]
        runner = self.jobs[key]
        snapshot = runner.snapshot()
        runs = recent_runs(self.connection, key, 1)
        state = snapshot.get("state", "idle")
        if self.is_running(key):
            state = "running"
        if state not in {"running", "failed"} and not self.enabled(spec):
            state = "paused"
        last_run = runs[0] if runs else None
        if last_run is not None:
            fields = (
                "id",
                "started_at",
                "finished_at",
                "outcome",
                "error",
                "model_tokens",
                "cost_usd",
            )
            last_run = {field: last_run[field] for field in fields}
        return {
            "key": spec.key,
            "title": spec.title,
            "enabled": self.enabled(spec),
            "spends_model_usage": spec.spends_model_usage,
            "run_budget_usd": spec.run_budget_usd,
            "run_budget_tokens": get_budget(self.connection, spec),
            "schedule_time": runner.schedule_time,
            "next_run_at": snapshot.get("next_run_at"),
            "state": state,
            "last_run": last_run,
            "warnings": _list_value(snapshot.get("warnings")),
            "failures": _list_value(snapshot.get("failures")),
            "summary_error": snapshot.get("summary_error"),
            "budget_exhausted": snapshot.get("budget_exhausted", False),
            "coverage": snapshot.get("coverage"),
        }


def create_jobs_routes(controller: JobsController) -> list[Route]:
    async def list_jobs(request: Request) -> JSONResponse:
        return JSONResponse(
            {"jobs": [controller.job(spec.key) for spec in BUILTIN_JOBS]}
        )

    async def runs(request: Request) -> JSONResponse:
        key = request.path_params["key"]
        if key not in JOBS_BY_KEY:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            return JSONResponse({"error": "invalid limit"}, status_code=400)
        return JSONResponse({"runs": recent_runs(controller.connection, key, limit)})

    async def change(request: Request) -> JSONResponse:
        key = request.path_params["key"]
        if key not in JOBS_BY_KEY:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        action = request.path_params["action"]
        if action not in {"pause", "resume", "run"}:
            return JSONResponse({"error": "unknown job action"}, status_code=404)
        if action == "run":
            await controller.run_in_background(key)
        else:
            set_enabled(controller.connection, JOBS_BY_KEY[key], action == "resume")
        return JSONResponse(controller.job(key))

    async def budget(request: Request) -> JSONResponse:
        key = request.path_params["key"]
        if key not in JOBS_BY_KEY:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        spec = JOBS_BY_KEY[key]
        if spec.run_budget_tokens is None:
            return JSONResponse({"error": "job has no token budget"}, status_code=400)
        try:
            payload = await request.json()
        except ValueError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        value = payload.get("run_budget_tokens") if isinstance(payload, dict) else None
        if not isinstance(value, int) or isinstance(value, bool):
            return JSONResponse(
                {"error": "run_budget_tokens must be an integer"}, status_code=400
            )
        try:
            set_budget(controller.connection, spec, value)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return JSONResponse(controller.job(key))

    return [
        Route("/api/jobs", list_jobs),
        Route("/api/jobs/{key:str}/runs", runs),
        Route("/api/jobs/{key:str}/budget", budget, methods=["PUT"]),
        Route("/api/jobs/{key:str}/{action:str}", change, methods=["POST"]),
    ]


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
