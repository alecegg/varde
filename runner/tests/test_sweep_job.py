from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime

from varde_runner.sweep_job import next_run_at, parse_sweep_output


def test_parse_sweep_output_reads_cli_json_contract():
    result = parse_sweep_output(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "run_at": "2026-10-22T03:00:00+00:00",
                    "sessions_seen": 8,
                    "analyzed": 5,
                    "skipped": 3,
                    "friction_added": 2,
                    "failures": [{"repo": "repo", "error": "bad"}],
                    "summary_error": "invalid summary config",
                },
            }
        )
    )
    assert result["counts"] == {
        "sessions_seen": 8,
        "analyzed": 5,
        "skipped": 3,
        "friction_added": 2,
    }
    assert len(result["failures"]) == 1
    assert result["summary_error"] == "invalid summary config"


def test_next_run_at_catches_up_or_uses_daily_configured_time():
    now = datetime(2026, 10, 22, 2, 0, tzinfo=UTC)
    assert next_run_at(now, "03:00", None) == datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
    assert next_run_at(now, "03:00", datetime(2026, 10, 21, 3, 0, tzinfo=UTC)) == now
    assert next_run_at(
        datetime(2026, 10, 22, 4, 0, tzinfo=UTC),
        "03:00",
        datetime(2026, 10, 22, 3, 0, tzinfo=UTC),
    ) == datetime(2026, 10, 23, 3, 0, tzinfo=UTC)


def test_invalid_schedule_time_falls_back_with_warning(caplog):
    from varde_runner.sweep_job import configured_schedule_time

    assert configured_schedule_time("24:00") == "03:00"
    assert "using 03:00 UTC" in caplog.text


def test_info_failure_is_mailbox_all_but_not_an_open_decision():
    from varde_runner.open_decisions import open_decision_items
    from varde_runner.web.app import _mailbox_payload

    messages = [
        {
            "msg_id": "question",
            "kind": "needs-user",
            "state": "pending",
            "sender": "worker",
            "ts": "1",
        },
        {
            "msg_id": "failure",
            "kind": "info-failure",
            "state": "pending",
            "sender": "runner",
            "ts": "2",
        },
    ]
    opened = open_decision_items(messages, [], set(), {"worker", "runner"}, set())
    mailbox = _mailbox_payload(messages)
    assert [item["msg_id"] for item in opened] == ["question"]
    assert [item["msg_id"] for item in mailbox["all"]] == ["question", "failure"]
    assert [item["msg_id"] for item in mailbox["open"]] == ["question"]


def test_info_failure_projects_as_information_only(tmp_path):
    from varde_runner.decisions import DecisionStore
    from varde_runner.intake import InboxProjector

    messages = [
        {
            "id": "failure-1",
            "from": "varde-runner",
            "to": "main",
            "kind": "info-failure",
            "text": "sweep-run:2026-10-22T03:00:00+00:00 failed",
            "ts": "2026-10-22T03:00:00+00:00",
        }
    ]
    decisions = DecisionStore(
        tmp_path / "decisions",
        send=lambda **_kwargs: {},
        read_messages=lambda: messages,
    )
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=lambda: messages,
        read_plan=lambda: {"events": []},
        decision_store=decisions,
    )

    projected = projector.project()
    decision = decisions.get_decision("failure-1")
    assert projected[0].kind == "info-failure"
    assert projected[0].type == "info"
    assert decision is not None
    assert decision["kind"] == "info"


def test_runner_catches_up_a_missed_day(tmp_path):
    from varde_runner.sweep_job import SweepClock, SweepJob

    now = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
    state_path = tmp_path / "sweep.json"
    state_path.write_text(json.dumps({"last_run_at": "2026-10-21T03:00:00+00:00"}))
    runs = []

    async def execute():
        runs.append(now)
        return (
            0,
            json.dumps(
                {
                    "data": {
                        "run_at": now.isoformat(),
                        "sessions_seen": 1,
                        "analyzed": 1,
                        "skipped": 0,
                        "friction_added": 0,
                        "summary_error": "summary unavailable",
                        "failures": [],
                    }
                }
            ),
            "",
        )

    async def stop_after_catch_up(_delay):
        raise asyncio.CancelledError

    job = SweepJob(
        state_path,
        execute=execute,
        schedule_time="03:00",
        clock=SweepClock(now=lambda: now, sleep=stop_after_catch_up),
    )

    async def exercise():
        with suppress(asyncio.CancelledError):
            await job.run()

    asyncio.run(exercise())
    assert runs == [now]


def test_sweep_warnings_and_failures_remain_distinct_without_failing(tmp_path):
    from varde_runner.sweep_job import SweepJob

    runs = 0
    notices = []

    async def execute():
        nonlocal runs
        runs += 1
        return (
            0,
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "run_at": "2026-10-22T03:00:00+00:00",
                        "sessions_seen": 3,
                        "analyzed": 1,
                        "skipped": 2,
                        "friction_added": 0,
                        "failures": [{"error": "inspect failed"}],
                        "warnings": [{"warning": "discovery incomplete"}],
                    },
                }
            ),
            "",
        )

    async def notify(run_id, message):
        notices.append((run_id, message))

    async def messages():
        return [
            {"kind": "info-failure", "text": f"sweep-run:{run_id}"}
            for run_id, _ in notices
        ]

    path = tmp_path / "sweep.json"
    job = SweepJob(path, execute=execute, notify=notify, messages=messages)

    async def exercise():
        snapshot = await job.run_now()
        assert snapshot["last_run_at"] == "2026-10-22T03:00:00+00:00"
        assert snapshot["counts"]["analyzed"] == 1
        assert snapshot["state"] == "succeeded"
        assert len(snapshot["failures"]) == 1
        assert snapshot["warnings"] == [{"warning": "discovery incomplete"}]
        assert snapshot["failures"] == [{"error": "inspect failed"}]
        assert notices == []

        restarted = SweepJob(path, execute=execute, notify=notify, messages=messages)
        assert restarted.snapshot()["warnings"] == [{"warning": "discovery incomplete"}]
        assert runs == 1

    asyncio.run(exercise())


def test_long_warning_and_failure_entries_do_not_notify_or_duplicate(tmp_path):
    from varde_runner.sweep_job import SweepClock, SweepJob

    now = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
    delivery = []
    continued = []
    failures = [{"error": f"failure-{index}-" + "x" * 200} for index in range(5)]
    warnings = [{"warning": "discovery was incomplete"}]

    async def execute():
        return (
            0,
            json.dumps(
                {
                    "data": {
                        "run_at": now.isoformat(),
                        "sessions_seen": 5,
                        "analyzed": 0,
                        "skipped": 5,
                        "friction_added": 0,
                        "failures": failures,
                        "warnings": warnings,
                    }
                }
            ),
            "",
        )

    def notify(run_id, message):
        delivery.append((run_id, message))
        raise RuntimeError("mailbox unavailable")

    async def sleep(_delay):
        continued.append(True)
        raise asyncio.CancelledError

    job = SweepJob(
        tmp_path / "sweep.json",
        execute=execute,
        notify=notify,
        schedule_time="03:00",
        clock=SweepClock(now=lambda: now, sleep=sleep),
    )

    async def exercise():
        with suppress(asyncio.CancelledError):
            await job.run()

    asyncio.run(exercise())
    assert delivery == []
    assert job.state["state"] == "succeeded"
    assert job.state["warnings"] == warnings
    assert job.state["failures"] == failures
    assert continued == [True]


def test_running_state_preserves_last_successful_counts(tmp_path):
    from varde_runner.sweep_job import SweepJob

    path = tmp_path / "sweep.json"
    last_counts = {
        "sessions_seen": 20,
        "analyzed": 18,
        "skipped": 2,
        "friction_added": 4,
    }
    path.write_text(
        json.dumps({"counts": last_counts, "failures": [], "state": "succeeded"})
    )

    async def execute():
        running = json.loads(path.read_text())
        assert running["state"] == "running"
        assert running["counts"] == last_counts
        return (
            0,
            json.dumps(
                {
                    "data": {
                        "run_at": "2026-10-22T03:00:00+00:00",
                        "failures": [],
                    }
                }
            ),
            "",
        )

    asyncio.run(SweepJob(path, execute=execute).run_now())


def test_status_and_run_now_routes_return_snapshot_fields(tmp_path):
    from varde_runner.web.app import create_app

    calls = []

    async def execute():
        calls.append(True)
        return (
            0,
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "run_at": "2026-10-22T03:00:00+00:00",
                        "sessions_seen": 1,
                        "analyzed": 1,
                        "skipped": 0,
                        "friction_added": 0,
                        "summary_error": "summary unavailable",
                        "failures": [
                            {"repo": f"repo-{index}", "error": "x" * 200}
                            for index in range(5)
                        ],
                    },
                }
            ),
            "",
        )

    class FakeCLI:
        def __init__(self):
            self.messages = []

        def send(self, **_kwargs):
            self.messages.append(
                {
                    "id": "failure-1",
                    "from": _kwargs["sender"],
                    "to": _kwargs["recipient"],
                    "kind": _kwargs["kind"],
                    "text": _kwargs["text"],
                    "ts": "2026-10-22T03:00:00+00:00",
                    "notes": _kwargs["notes"],
                }
            )
            return {}

        def read_messages(self):
            return self.messages

        def read_plan(self):
            return {"events": [], "plans": []}

        def read_address_bindings(self):
            return []

        def read_message_status(self):
            return {"messages": []}

        def read_concluded_addresses(self):
            return []

    fake_cli = FakeCLI()
    app = create_app(data_dir=tmp_path, cli=fake_cli, agents=list)
    app.state.sweep_job.execute = execute

    async def request(method, path):
        response = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            response.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"host", b"localhost:8765"),
                    (b"origin", b"http://localhost:8765"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8765),
            },
            receive,
            send,
        )
        return json.loads(b"".join(row.get("body", b"") for row in response))

    async def exercise():
        status = await request("GET", "/api/learn/sweep")
        assert set(status) >= {
            "last_run_at",
            "counts",
            "failures",
            "next_run_at",
            "state",
        }, status
        result = await request("POST", "/api/learn/sweep/run")
        assert result["last_run_at"] == "2026-10-22T03:00:00+00:00"
        assert result["counts"]["sessions_seen"] == 1
        assert result["state"] == "succeeded"
        assert result["summary_error"] == "summary unavailable"
        assert len(calls) == 1
        assert fake_cli.messages == []

        jobs_result = await request("POST", "/api/jobs/sweep/run")
        assert jobs_result["state"] == "succeeded"
        runs = await request("GET", "/api/jobs/sweep/runs")
        assert runs["runs"][0]["outcome"] == "succeeded"
        assert runs["runs"][0]["error"] is None
        assert runs["runs"][0]["id"] > 0

        mailbox = await request("GET", "/api/mailbox")
        assert mailbox["all"] == []
        assert mailbox["open"] == []

    asyncio.run(exercise())
