import logging
from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from varde_runner.daily_job import (
    configured_schedule_time,
    next_run_at,
    parse_datetime,
    parse_scheduled_time,
)


def test_parse_scheduled_time_validates_and_uses_utc():
    assert parse_scheduled_time("03:15", "bad time") == time(3, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="bad time"):
        parse_scheduled_time("25:00", "bad time")


def test_configured_schedule_time_falls_back_and_logs(caplog):
    with caplog.at_level(logging.WARNING):
        result = configured_schedule_time(
            "invalid",
            error_message="bad time",
            environment_name="VARDE_TEST_TIME",
            default="03:15",
            logger=logging.getLogger("test_daily_job"),
        )

    assert result == "03:15"
    assert "Invalid VARDE_TEST_TIME 'invalid'; using 03:15 UTC" in caplog.text


def test_next_run_at_uses_supplied_past_run_policy():
    now = datetime(2026, 10, 23, 4, tzinfo=UTC)
    last_run = datetime(2026, 10, 22, 3, 15, tzinfo=UTC)

    assert (
        next_run_at(
            now,
            "03:15",
            last_run,
            past_run_result=lambda current, _scheduled: current,
            error_message="bad time",
        )
        == now
    )
    assert (
        next_run_at(
            now,
            "03:15",
            last_run,
            past_run_result=max,
            error_message="bad time",
        )
        == now
    )
    assert next_run_at(
        datetime(2026, 10, 23, 2, tzinfo=UTC),
        "03:15",
        last_run,
        past_run_result=max,
        error_message="bad time",
    ) == datetime(2026, 10, 23, 3, 15, tzinfo=UTC)


def test_parse_datetime_accepts_naive_and_aware_values():
    assert parse_datetime("2026-10-23T03:15:00") == datetime(
        2026, 10, 23, 3, 15, tzinfo=UTC
    )
    assert parse_datetime("2026-10-23T03:15:00+02:00") == datetime(
        2026, 10, 23, 3, 15, tzinfo=timezone(timedelta(hours=2))
    )
    assert parse_datetime("not a datetime") is None
    assert parse_datetime(None) is None


def test_paused_job_rechecks_every_minute_and_manual_run_is_recorded(tmp_path):
    import asyncio
    import json
    from contextlib import suppress

    from varde_runner.sweep_job import SweepClock, SweepJob

    now = datetime(2026, 10, 23, 4, 30, tzinfo=UTC)
    sleeps = []
    records = []
    executed = []
    enabled = False

    async def sleep(delay):
        sleeps.append(delay)
        raise asyncio.CancelledError

    async def execute():
        executed.append(True)
        return (
            0,
            json.dumps(
                {
                    "data": {
                        "run_at": now.isoformat(),
                        "sessions_seen": 0,
                        "analyzed": 0,
                        "skipped": 0,
                        "friction_added": 0,
                        "failures": [],
                    }
                }
            ),
            "",
        )

    job = SweepJob(
        tmp_path / "sweep.json",
        execute=execute,
        schedule_time="03:00",
        clock=SweepClock(now=lambda: now, sleep=sleep),
        enabled_check=lambda: enabled,
        run_recorder=lambda trigger, snapshot: records.append((trigger, snapshot)),
    )

    async def exercise():
        nonlocal enabled
        with suppress(asyncio.CancelledError):
            await job._run_scheduled_iteration()
        enabled = True
        await job._run_scheduled_iteration()
        await job.run_now()

    asyncio.run(exercise())

    assert sleeps == [60]
    assert executed == [True, True]
    assert [trigger for trigger, _snapshot in records] == ["schedule", "manual"]
    assert all(snapshot["state"] == "succeeded" for _trigger, snapshot in records)
