import asyncio
import json
import threading

from starlette.applications import Starlette
from varde_runner.job_store import finish_run, open_job_store, recent_runs, start_run
from varde_runner.sweep_job import SweepJob
from varde_runner.web.jobs_route import JobsController, create_jobs_routes


class _Job:
    def __init__(self, state="idle"):
        self.state = state
        self.schedule_time = "03:00"
        self.run_count = 0

    def snapshot(self):
        return {
            "state": self.state,
            "next_run_at": "2026-10-24T03:00:00+00:00",
            "warnings": [],
            "failures": [],
            "summary_error": None,
        }

    async def run_now(self):
        self.run_count += 1
        self.state = "succeeded"


def _request(app, path, method="GET", body=None):
    async def dispatch():
        raw_path, _, query = path.partition("?")
        messages = []

        async def receive():
            if isinstance(body, bytes):
                request_body = body
            elif body is not None:
                request_body = json.dumps(body).encode()
            else:
                request_body = b""
            return {"type": "http.request", "body": request_body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": raw_path,
                "raw_path": raw_path.encode(),
                "query_string": query.encode(),
                "root_path": "",
                "headers": [
                    (b"host", b"localhost"),
                    (b"content-type", b"application/json"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(item for item in messages if item["type"] == "http.response.start")
        response_body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return start["status"], json.loads(response_body)

    return asyncio.run(dispatch())


def test_jobs_api_lists_failure_history_and_actions(tmp_path):
    connection = open_job_store(tmp_path)
    jobs = {"sweep": _Job("failed"), "soak": _Job(), "review": _Job()}
    jobs["sweep"].snapshot = lambda: {
        "state": jobs["sweep"].state,
        "next_run_at": "2026-10-24T03:00:00+00:00",
        "warnings": [{"warning": "discovery incomplete"}],
        "failures": [{"error": "session unreadable"}],
        "summary_error": "summary unavailable",
    }
    jobs["review"].snapshot = lambda: {
        "state": "idle",
        "next_run_at": "2026-10-24T04:00:00+00:00",
        "budget_exhausted": True,
        "coverage": {"found": 5, "analyzed": 2, "skipped": 3, "failed": 0},
    }
    controller = JobsController(connection, jobs)
    app = Starlette(routes=create_jobs_routes(controller))
    try:
        run_id = start_run(connection, "sweep", "schedule")
        finish_run(connection, run_id, outcome="failed", error="sweep broke")
        status, response = _request(app, "/api/jobs")
        assert status == 200
        sweep = next(job for job in response["jobs"] if job["key"] == "sweep")
        assert sweep["last_run"]["error"] == "sweep broke"
        assert sweep["last_run"]["outcome"] == "failed"
        assert sweep["warnings"] == [{"warning": "discovery incomplete"}]
        assert sweep["failures"] == [{"error": "session unreadable"}]
        assert sweep["summary_error"] == "summary unavailable"
        review = next(job for job in response["jobs"] if job["key"] == "review")
        assert review["enabled"] is False
        assert review["spends_model_usage"] is True
        assert review["budget_exhausted"] is True
        assert review["coverage"]["found"] == 5

        status, response = _request(app, "/api/jobs/sweep/runs?limit=5")
        assert status == 200
        assert response["runs"][0]["error"] == "sweep broke"
        assert _request(app, "/api/jobs/missing/runs")[0] == 404
        assert _request(app, "/api/jobs/sweep/pause", "POST")[1]["enabled"] is False
        assert _request(app, "/api/jobs/sweep/nope", "POST")[0] == 404
        assert _request(app, "/api/jobs")[1]["jobs"][0]["enabled"] is False
        jobs["sweep"].state = "failed"
        assert _request(app, "/api/jobs")[1]["jobs"][0]["state"] == "failed"
        jobs["sweep"].schedule_time = "04:30"
        assert _request(app, "/api/jobs")[1]["jobs"][0]["schedule_time"] == "04:30"
        assert _request(app, "/api/jobs/sweep/resume", "POST")[1]["enabled"] is True
        assert _request(app, "/api/jobs/soak/run", "POST")[1]["state"] == "succeeded"
        manual_review = _request(app, "/api/jobs/review/run", "POST")
        assert manual_review[0] == 200
        assert manual_review[1]["enabled"] is False
        assert jobs["review"].run_count == 1
    finally:
        connection.close()


def test_budget_route_validates_and_persists_without_enabling(tmp_path):
    connection = open_job_store(tmp_path)
    jobs = {"sweep": _Job(), "soak": _Job(), "review": _Job()}
    app = Starlette(routes=create_jobs_routes(JobsController(connection, jobs)))

    def put_budget(key, payload):
        return _request(app, f"/api/jobs/{key}/budget", "PUT", payload)[0]

    try:
        status, job = _request(
            app, "/api/jobs/review/budget", "PUT", {"run_budget_tokens": 1234}
        )
        assert status == 200 and job["enabled"] is False
        assert job["run_budget_tokens"] == 1234
        assert (
            _request(app, "/api/jobs/nope/budget", "PUT", {"run_budget_tokens": 1234})[
                0
            ]
            == 404
        )
        assert (
            _request(app, "/api/jobs/review/budget", "PUT", {"run_budget_tokens": 0})[0]
            == 400
        )
        assert put_budget("review", {"run_budget_tokens": 10_000_001}) == 400
        assert put_budget("review", {"run_budget_tokens": True}) == 400
        assert put_budget("review", {"run_budget_tokens": "12"}) == 400
        assert put_budget("review", [1234]) == 400
        assert put_budget("review", b"not-json") == 400
        assert put_budget("sweep", {"run_budget_tokens": 1}) == 400
    finally:
        connection.close()


def test_review_run_history_records_tokens_and_cost(tmp_path):
    connection = open_job_store(tmp_path)
    controller = JobsController(
        connection, {"sweep": _Job(), "soak": _Job(), "review": _Job()}
    )
    try:
        run_id = controller.start("review", "manual")
        controller.finish(
            "review",
            run_id,
            {
                "state": "succeeded",
                "model_tokens": 567,
                "cost_usd": 0.031,
                "error": None,
            },
            None,
        )
        run = recent_runs(connection, "review")[0]
        assert run["outcome"] == "succeeded"
        assert run["model_tokens"] == 567
        assert run["cost_usd"] == 0.031
        assert run["error"] is None
    finally:
        connection.close()


def test_job_run_is_visible_while_execution_is_in_progress(tmp_path):
    connection = open_job_store(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    async def execute_sweep():
        entered.set()
        await asyncio.to_thread(release.wait)
        return (
            0,
            json.dumps(
                {
                    "data": {
                        "run_at": "2026-10-23T00:00:00+00:00",
                        "failures": [],
                    }
                }
            ),
            "",
        )

    job = SweepJob(tmp_path / "sweep.json", execute=execute_sweep)
    controller = JobsController(
        connection, {"sweep": job, "soak": _Job(), "review": _Job()}
    )
    job.run_started = lambda trigger: controller.start("sweep", trigger)
    job.run_finished = lambda run_id, snapshot, error: controller.finish(
        "sweep", run_id, snapshot, error
    )

    async def execute():
        task = asyncio.create_task(job.run_now())
        assert await asyncio.to_thread(entered.wait, 2)
        row = recent_runs(connection, "sweep")[0]
        assert row["outcome"] == "running"
        assert row["finished_at"] is None
        release.set()
        await task

    try:
        asyncio.run(execute())
        assert recent_runs(connection, "sweep")[0]["outcome"] == "succeeded"
    finally:
        connection.close()


class _SlowJob(_Job):
    def __init__(self, controller, fail=False):
        super().__init__()
        self.controller = controller
        self.fail = fail
        self.release = asyncio.Event()

    async def run_now(self):
        run_id = self.controller.start("sweep", "manual")
        self.run_count += 1
        await self.release.wait()
        error = RuntimeError("boom") if self.fail else None
        self.controller.finish("sweep", run_id, {}, error)
        if error:
            raise error


def _slow_controller(tmp_path, fail=False):
    connection = open_job_store(tmp_path / "jobs.db")
    controller = JobsController(connection, {})
    job = _SlowJob(controller, fail)
    controller.jobs["sweep"] = job
    return connection, controller, job


def test_run_returns_running_entry_and_ignores_duplicate_post(tmp_path):
    connection, controller, job = _slow_controller(tmp_path)

    async def scenario():
        await asyncio.gather(
            controller.run_in_background("sweep"),
            controller.run_in_background("sweep"),
        )
        assert controller.job("sweep")["state"] == "running"
        assert job.run_count == 1
        job.release.set()
        await asyncio.gather(*controller.manual_runs.values())
        assert controller.job("sweep")["last_run"]["outcome"] == "succeeded"

    try:
        asyncio.run(scenario())
    finally:
        connection.close()


def test_background_run_failure_is_recorded_without_task_error(tmp_path):
    connection, controller, job = _slow_controller(tmp_path, fail=True)

    async def scenario():
        await controller.run_in_background("sweep")
        job.release.set()
        await asyncio.wait(list(controller.manual_runs.values()))
        await asyncio.sleep(0)
        assert not controller.manual_runs
        last = controller.job("sweep")["last_run"]
        assert last["outcome"] == "failed"
        assert last["error"] == "boom"

    try:
        asyncio.run(scenario())
    finally:
        connection.close()
