from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from varde_runner.config import MAIL_SOAK_SCHEDULE_ENV
from varde_runner.soak_job import (
    SoakClock,
    SoakJob,
    configured_schedule_time,
    next_run_at,
    parse_soak_output,
)
from varde_runner.web.app import create_app


class FakeCLI:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.env = {}

    def send(self, **_kwargs):
        return {}

    def read_messages(self):
        return []

    def read_plan(self):
        return {"events": [], "plans": []}

    def read_address_bindings(self):
        return []

    def read_message_status(self):
        return {"messages": []}

    def read_concluded_addresses(self):
        return []


def test_parse_soak_output_accepts_failing_report_as_a_valid_result():
    report = {
        "date": "2026-10-23",
        "window_days": 3,
        "criteria": [],
        "active_orchestrators": 1,
        "all_ok": False,
        "days_ok_streak": 0,
    }
    assert parse_soak_output(json.dumps(report)) == report


def test_next_run_at_catches_up_a_missed_daily_run():
    now = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    assert next_run_at(now, "03:15", datetime(2026, 10, 22, 3, 15, tzinfo=UTC)) == now


def test_next_run_at_waits_until_schedule_after_overnight_restart():
    now = datetime(2026, 10, 23, 0, 30, tzinfo=UTC)
    previous_run = datetime(2026, 10, 22, 3, 15, tzinfo=UTC)

    assert next_run_at(now, "03:15", previous_run) == datetime(
        2026, 10, 23, 3, 15, tzinfo=UTC
    )


def test_next_run_at_skips_second_run_on_same_day():
    now = datetime(2026, 10, 23, 4, 0, tzinfo=UTC)

    assert next_run_at(
        now, "03:15", datetime(2026, 10, 23, 3, 15, tzinfo=UTC)
    ) == datetime(2026, 10, 24, 3, 15, tzinfo=UTC)


def test_invalid_schedule_time_uses_default_with_warning(caplog):
    assert configured_schedule_time("25:00") == "03:15"
    assert "using 03:15 UTC" in caplog.text


def test_job_persists_report_when_cli_uses_failure_exit_code(tmp_path):
    report = {
        "date": "2026-10-23",
        "window_days": 3,
        "criteria": [],
        "active_orchestrators": 1,
        "all_ok": False,
        "days_ok_streak": 0,
    }
    executed = []

    async def execute():
        executed.append(True)
        return 1, json.dumps(report), ""

    now = datetime(2026, 10, 23, 3, 15, tzinfo=UTC)
    job = SoakJob(
        tmp_path / "state.json",
        execute=execute,
        clock=SoakClock(now=lambda: now),
    )

    snapshot = asyncio.run(job.run_now())

    assert snapshot["state"] == "succeeded"
    assert snapshot["report"] == report
    assert json.loads((tmp_path / "state.json").read_text())["report"] == report
    assert executed == [True]


def test_job_records_failure_and_deduplicates_notification(tmp_path):
    notices = []
    messages = []

    async def execute():
        return 70, "", "CLI failed"

    def notify(run_id, message):
        notices.append((run_id, message))
        messages.append({"kind": "info-failure", "text": message})

    now = datetime(2026, 10, 23, 3, 15, tzinfo=UTC)
    state_path = tmp_path / "state.json"
    job = SoakJob(
        state_path,
        execute=execute,
        notify=notify,
        messages=lambda: messages,
        clock=SoakClock(now=lambda: now),
    )

    snapshot = asyncio.run(job.run_now())

    assert snapshot["state"] == "failed"
    assert snapshot["error"] == "CLI failed"
    assert job.state["notification_pending"] is None
    assert len(notices) == 1
    job.state["notification_pending"] = {
        "run_id": notices[0][0],
        "message": notices[0][1],
    }
    asyncio.run(job.resume_notification())
    assert len(notices) == 1


def test_run_logs_and_retries_when_state_save_fails(caplog, tmp_path):
    sleeps = []
    now = datetime(2026, 10, 23, 3, 15, tzinfo=UTC)

    async def execute():
        raise AssertionError("execute must not run if the initial save fails")

    async def stop_after_retry(delay):
        sleeps.append(delay)
        raise asyncio.CancelledError

    job = SoakJob(
        tmp_path / "state.json",
        execute=execute,
        clock=SoakClock(now=lambda: now, sleep=stop_after_retry),
    )

    def fail_save():
        raise OSError("disk unavailable")

    job._save = fail_save

    with caplog.at_level(logging.ERROR), suppress(asyncio.CancelledError):
        asyncio.run(job.run())

    assert sleeps == [60]
    assert "Mail soak job failed; retrying in 60 seconds" in caplog.text


def test_app_uses_configured_mail_soak_schedule(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv(MAIL_SOAK_SCHEDULE_ENV, "invalid")

    app = create_app(data_dir=tmp_path / "data", cli=FakeCLI(tmp_path))

    assert app.state.soak_job.schedule_time == "03:15"
    assert "Invalid VARDE_MAIL_SOAK_TIME" in caplog.text


def test_app_runs_soak_through_varde_cli_boundary(tmp_path, monkeypatch):
    working = tmp_path / "working"
    app = create_app(data_dir=tmp_path / "data", cli=FakeCLI(working))
    report = {
        "date": "2026-10-23",
        "window_days": 3,
        "criteria": [],
        "active_orchestrators": 1,
        "all_ok": False,
        "days_ok_streak": 0,
    }
    calls = []

    class Process:
        returncode = 1

        async def communicate(self):
            return json.dumps(report).encode(), b""

    async def create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr(
        "varde_runner.web.app.asyncio.create_subprocess_exec", create_subprocess_exec
    )

    snapshot = asyncio.run(app.state.soak_job.run_now())

    assert snapshot["report"] == report
    assert calls[0][0] == ("varde", "msg", "soak", "--write", "--json")
    assert calls[0][1]["cwd"] == working
    assert calls[0][1]["env"]["VARDE_WORKING_DIR"] == str(working)


def test_lifespan_starts_and_stops_both_daily_jobs(tmp_path, monkeypatch):
    from varde_runner.web import app as app_module

    app = create_app(data_dir=tmp_path / "data", cli=FakeCLI(tmp_path))
    monkeypatch.setattr(
        app_module, "_prewarm_dashboard", lambda *_args: _skip_prewarm()
    )
    started = {"sweep": asyncio.Event(), "soak": asyncio.Event()}
    stopped = {"sweep": asyncio.Event(), "soak": asyncio.Event()}

    def blocking_run(name):
        async def run():
            started[name].set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped[name].set()
                raise

        return run

    app.state.sweep_job.run = blocking_run("sweep")
    app.state.soak_job.run = blocking_run("soak")

    async def exercise():
        async with app.router.lifespan_context(app):
            await asyncio.gather(*(event.wait() for event in started.values()))
        assert all(event.is_set() for event in stopped.values())

    asyncio.run(exercise())


async def _skip_prewarm():
    return None


async def _request(app, path: str) -> tuple[int, bytes]:
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost:8765")],
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 8765),
        },
        receive,
        send,
    )
    start = next(item for item in messages if item["type"] == "http.response.start")
    body = b"".join(
        item.get("body", b"")
        for item in messages
        if item["type"] == "http.response.body"
    )
    return start["status"], body


def test_mail_soak_route_returns_404_when_no_daily_report_exists(tmp_path):
    app = create_app(data_dir=tmp_path / "data", cli=FakeCLI(tmp_path))

    status, body = asyncio.run(_request(app, "/api/mail-soak"))

    assert status == 404
    assert json.loads(body) == {"error": "mail soak report not found"}


def test_mail_soak_route_returns_latest_daily_report(tmp_path):
    working = tmp_path / "working"
    reports = working / "metrics" / "mail-soak"
    reports.mkdir(parents=True)
    older = {"date": "2026-10-22", "all_ok": False}
    latest = {"date": "2026-10-23", "all_ok": True, "days_ok_streak": 3}
    (reports / "2026-10-22.json").write_text(json.dumps(older))
    (reports / "2026-10-23.json").write_text(json.dumps(latest))
    app = create_app(data_dir=tmp_path / "data", cli=FakeCLI(working))

    status, body = asyncio.run(_request(app, "/api/mail-soak"))

    assert status == 200
    assert json.loads(body) == latest


def test_mail_soak_route_skips_corrupt_and_non_date_report_files(tmp_path):
    working = tmp_path / "working"
    reports = working / "metrics" / "mail-soak"
    reports.mkdir(parents=True)
    valid = {"date": "2026-10-22", "all_ok": False}
    (reports / "2026-10-22.json").write_text(json.dumps(valid))
    (reports / "2026-10-23.json").write_bytes(b"\xffnot json")
    (reports / "latest.json").write_text(json.dumps({"date": "2026-10-24"}))
    (reports / "2026-99-99.json").write_text(json.dumps({"date": "bad"}))
    app = create_app(data_dir=tmp_path / "data", cli=FakeCLI(working))

    status, body = asyncio.run(_request(app, "/api/mail-soak"))

    assert status == 200
    assert json.loads(body) == valid
