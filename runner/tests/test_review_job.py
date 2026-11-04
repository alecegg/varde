import asyncio
import json

import pytest
from starlette.requests import Request
from starlette.routing import Route
from varde_runner.job_registry import JOBS_BY_KEY
from varde_runner.job_store import open_job_store, set_budget
from varde_runner.review_job import (
    DEFAULT_REVIEW_TIMEOUT_SECONDS,
    ReviewJob,
    _raise_review_failure,
    configured_timeout_seconds,
    execute_review_cli,
    parse_review_output,
)
from varde_runner.web.app import create_app


def test_review_job_parses_cli_stdout_and_snapshots_usage(tmp_path):
    payload = {
        "data": {
            "run_at": "2026-10-23T04:00:00+00:00",
            "model_tokens": 812,
            "cost_usd_estimate": 0.024,
            "budget_tokens": 900,
            "budget_exhausted": True,
            "coverage": {"found": 6, "analyzed": 4, "skipped": 1, "failed": 1},
            "report_path": "/workspace/review.md",
        }
    }
    stdout = json.dumps(payload)
    assert parse_review_output(stdout)["model_tokens"] == 812

    async def execute():
        return 0, stdout, ""

    job = ReviewJob(tmp_path / "review.json", execute=execute)
    snapshot = asyncio.run(job.run_now())
    assert snapshot["state"] == "succeeded"
    assert snapshot["model_tokens"] == 812
    assert snapshot["cost_usd"] == 0.024
    assert snapshot["budget_tokens"] == 900
    assert snapshot["budget_exhausted"] is True
    assert snapshot["coverage"]["found"] == 6
    assert snapshot["report_path"] == "/workspace/review.md"


def test_review_snapshot_includes_pending_and_stop_details():
    parsed = parse_review_output(
        json.dumps(
            {
                "run_at": "2026-10-23T04:00:00+00:00",
                "stop_reason": "failed",
                "stop_error": "invalid model",
                "coverage": {
                    "found": 2,
                    "analyzed": 0,
                    "skipped": 0,
                    "failed": 1,
                    "pending": 1,
                },
            }
        )
    )
    assert parsed["stop_reason"] == "failed"
    assert parsed["stop_error"] == "invalid model"
    assert parsed["coverage"]["pending"] == 1


def test_review_cli_failure_redacts_before_job_state_storage():
    with pytest.raises(RuntimeError) as failure:
        _raise_review_failure("token=sk-abcdefghijklmnopqrstuvwxyz", "", 1)
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(failure.value)


def test_review_job_persists_cli_failure(tmp_path):
    async def execute():
        return 1, "", "learn review failed"

    job = ReviewJob(tmp_path / "review.json", execute=execute)
    snapshot = asyncio.run(job.run_now())
    assert snapshot["state"] == "failed"
    assert snapshot["error"] == "learn review failed"


def test_review_success_clears_previous_error(tmp_path):
    success = json.dumps({"data": {"run_at": "2026-10-23T04:00:00+00:00"}})
    results = iter([(1, "", "first failure"), (0, success, "")])

    async def execute():
        return next(results)

    job = ReviewJob(tmp_path / "review.json", execute=execute)
    assert asyncio.run(job.run_now())["error"] == "first failure"
    snapshot = asyncio.run(job.run_now())
    assert snapshot["state"] == "succeeded"
    assert snapshot["error"] is None


def test_review_parser_rejects_malformed_usage_and_coverage():
    invalid_tokens = json.dumps(
        {"data": {"run_at": "2026-10-23T04:00:00+00:00", "model_tokens": "12"}}
    )
    with pytest.raises(ValueError, match="model_tokens"):
        parse_review_output(invalid_tokens)
    invalid_coverage = json.dumps(
        {"data": {"run_at": "2026-10-23T04:00:00+00:00", "coverage": []}}
    )
    with pytest.raises(TypeError, match="coverage"):
        parse_review_output(invalid_coverage)


def test_review_timeout_config_has_safe_default():
    assert configured_timeout_seconds(None) == DEFAULT_REVIEW_TIMEOUT_SECONDS
    assert configured_timeout_seconds("1200") == 1200
    assert configured_timeout_seconds("0") == DEFAULT_REVIEW_TIMEOUT_SECONDS


def test_execute_review_cli_uses_budget_argv_and_returns_fake_stdout(tmp_path):
    captured = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b'{"data":{}}', b""

        def kill(self):
            raise AssertionError("process should not be killed")

        async def wait(self):
            return None

    async def spawn(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    result = asyncio.run(
        execute_review_cli(
            budget_tokens=4321,
            cwd=tmp_path,
            environment={"VARDE_WORKING_DIR": str(tmp_path)},
            timeout_seconds=5,
            spawn=spawn,
        )
    )
    assert captured["args"] == (
        "varde",
        "learn",
        "run",
        "--json",
        "--window",
        "since-last",
        "--budget-tokens",
        "4321",
    )
    assert captured["kwargs"]["cwd"] == tmp_path
    assert result == (0, '{"data":{}}', "")


def test_execute_review_cli_kills_process_and_returns_failure_on_timeout(tmp_path):
    killed = []

    class Process:
        returncode = None

        async def communicate(self):
            await asyncio.Event().wait()

        def kill(self):
            killed.append(True)

        async def wait(self):
            return -9

    async def spawn(*_args, **_kwargs):
        return Process()

    result = asyncio.run(
        execute_review_cli(
            budget_tokens=4321,
            cwd=tmp_path,
            environment={},
            timeout_seconds=0.01,
            spawn=spawn,
        )
    )
    assert result == (124, "", "review timed out after 0.01 seconds")
    assert killed == [True]

    async def execute():
        return await execute_review_cli(
            budget_tokens=4321,
            cwd=tmp_path,
            environment={},
            timeout_seconds=0.01,
            spawn=spawn,
        )

    job = ReviewJob(tmp_path / "timeout.json", execute=execute)
    snapshot = asyncio.run(job.run_now())
    assert snapshot["state"] == "failed"
    assert snapshot["error"] == "review timed out after 0.01 seconds"
    assert killed == [True, True]


def test_app_review_uses_stored_budget_in_cli_argv(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    store = open_job_store(data_dir)
    set_budget(store, JOBS_BY_KEY["review"], 4321)
    store.close()

    class FakeCLI:
        def __init__(self):
            self.cwd = tmp_path / "working"
            self.env = {}

        def send(self, **_kwargs):
            return {}

        def read_plan(self):
            return {"events": [], "plans": []}

    app = create_app(data_dir=data_dir, cli=FakeCLI())
    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            return (
                json.dumps(
                    {
                        "data": {
                            "run_at": "2026-10-23T04:00:00+00:00",
                            "model_tokens": 321,
                            "cost_usd_estimate": 0.02,
                            "budget_tokens": 4321,
                            "budget_exhausted": False,
                            "coverage": {
                                "found": 1,
                                "analyzed": 1,
                                "skipped": 0,
                                "failed": 0,
                            },
                        }
                    }
                ).encode(),
                b"",
            )

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr("varde_runner.web.app.asyncio.create_subprocess_exec", spawn)
    route = next(
        route
        for route in app.routes
        if isinstance(route, Route) and route.path == "/api/jobs/{key:str}/{action:str}"
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/jobs/review/run",
            "raw_path": b"/api/jobs/review/run",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "path_params": {"key": "review", "action": "run"},
        }
    )
    response = asyncio.run(route.endpoint(request))

    assert calls[0][0] == (
        "varde",
        "learn",
        "run",
        "--json",
        "--window",
        "since-last",
        "--budget-tokens",
        "4321",
    )
    assert calls[0][1]["cwd"] == tmp_path / "working"
    assert response.status_code == 200
