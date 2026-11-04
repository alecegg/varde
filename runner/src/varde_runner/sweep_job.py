"""Daily runner job that invokes the learn sweep through its CLI boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from varde_runner.daily_job import (
    DailyJob,
    DailyJobClock,
    DailyJobConfig,
    parse_datetime,
    parse_scheduled_time,
)
from varde_runner.daily_job import (
    configured_schedule_time as _configured_schedule_time,
)
from varde_runner.daily_job import (
    next_run_at as _shared_next_run_at,
)

logger = logging.getLogger(__name__)


def _raise_sweep_failure(stderr: str, stdout: str, code: int) -> None:
    raise RuntimeError(stderr.strip() or stdout.strip() or f"sweep exited {code}")


def parse_sweep_output(stdout: str) -> dict[str, Any]:
    """Parse the JSON envelope emitted by ``varde learn sweep --json``."""
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise TypeError("sweep output must be a JSON object")
    data = value.get("data", value)
    if not isinstance(data, dict):
        raise TypeError("sweep output data must be a JSON object")
    counts = {
        name: _count(data.get(name))
        for name in ("sessions_seen", "analyzed", "skipped", "friction_added")
    }
    failures = data.get("failures", [])
    if not isinstance(failures, list):
        raise TypeError("sweep failures must be a list")
    warnings = data.get("warnings", [])
    if not isinstance(warnings, list):
        raise TypeError("sweep warnings must be a list")
    run_at = data.get("run_at")
    if not isinstance(run_at, str):
        raise TypeError("sweep output is missing run_at")
    datetime.fromisoformat(run_at)
    return {
        "run_at": run_at,
        "counts": counts,
        "failures": failures,
        "warnings": warnings,
        "digest": data.get("digest"),
        "model_tokens": data.get("model_tokens"),
        "summary_error": data.get("summary_error"),
    }


def _count(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return value


def _scheduled_time(value: str) -> time:
    return parse_scheduled_time(value, "sweep time must use 24-hour HH:MM format")


def configured_schedule_time(value: str) -> str:
    return _configured_schedule_time(
        value,
        error_message="sweep time must use 24-hour HH:MM format",
        environment_name="VARDE_LEARN_SWEEP_TIME",
        default="03:00",
        logger=logger,
    )


def next_run_at(
    now: datetime, schedule_time: str, last_run_at: datetime | None
) -> datetime:
    """Return today's configured time, a missed-run catch-up, or tomorrow."""
    return _shared_next_run_at(
        now,
        schedule_time,
        last_run_at,
        past_run_result=lambda current, _today: current,
        error_message="sweep time must use 24-hour HH:MM format",
    )


class SweepClock(DailyJobClock):
    pass


class SweepJob(DailyJob):
    """Persistent scheduled sweep with an idempotent failure notification."""

    def __init__(  # noqa: PLR0913 - expose the shared DailyJob control hooks
        self,
        state_path: Path,
        *,
        execute: Callable[[], Any],
        notify: Callable[[str, str], Any] | None = None,
        messages: Callable[[], Any] | None = None,
        schedule_time: str = "03:00",
        clock: SweepClock | None = None,
        enabled_check: Callable[[], Any] | None = None,
        run_recorder: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        _scheduled_time(schedule_time)
        super().__init__(
            DailyJobConfig(
                state_path=state_path,
                execute=execute,
                notify=notify,
                messages=messages,
                schedule_time=schedule_time,
                clock=clock or SweepClock(),
                empty_state={
                    "last_run_at": None,
                    "counts": {
                        "sessions_seen": 0,
                        "analyzed": 0,
                        "skipped": 0,
                        "friction_added": 0,
                    },
                    "failures": [],
                    "warnings": [],
                    "digest": None,
                    "model_tokens": None,
                    "summary_error": None,
                    "state": "idle",
                    "notification_pending": None,
                    "notification_sent": [],
                },
                temporary_prefix=".sweep-job-",
                notification_prefix="sweep-run:",
                logger=logger,
                notification_name="sweep",
                enabled_check=enabled_check,
                run_recorder=run_recorder,
            )
        )

    def _next_run_at(
        self, now: datetime, schedule_time: str, last_run: datetime | None
    ) -> datetime:
        return next_run_at(now, schedule_time, last_run)

    def snapshot(self) -> dict[str, Any]:
        last_run = _parse_datetime(self.state.get("last_run_at"))
        return {
            "last_run_at": self.state.get("last_run_at"),
            "counts": dict(self.state["counts"]),
            "failures": list(self.state["failures"]),
            "warnings": list(self.state.get("warnings", [])),
            "digest": self.state.get("digest"),
            "model_tokens": self.state.get("model_tokens"),
            "summary_error": self.state.get("summary_error"),
            "next_run_at": next_run_at(
                self.clock.now(), self.schedule_time, last_run
            ).isoformat(),
            "state": self.state["state"],
        }

    async def run_now(self) -> dict[str, Any]:
        return await self._run_and_record("manual")

    async def _execute_run(self) -> dict[str, Any]:
        async with self.lock:
            await self.resume_notification()
            self.state.update({"state": "running"})
            self._save()
            run_id = self.clock.now().astimezone(UTC).isoformat()
            try:
                code, stdout, stderr = await self.execute()
                if code:
                    _raise_sweep_failure(stderr, stdout, code)
                result = parse_sweep_output(stdout)
                self.state.update(
                    {
                        "last_run_at": result["run_at"],
                        "counts": result["counts"],
                        "failures": result["failures"],
                        "warnings": result["warnings"],
                        "digest": result["digest"],
                        "model_tokens": result["model_tokens"],
                        "summary_error": result["summary_error"],
                        "state": "succeeded",
                    }
                )
            except Exception as error:  # noqa: BLE001 - persist failed subprocess and parse results
                failure = {"error": str(error)[:500]}
                self.state.update(
                    {
                        "last_run_at": self.clock.now().astimezone(UTC).isoformat(),
                        "failures": [failure],
                        "state": "failed",
                    }
                )
                self.state["notification_pending"] = {
                    "run_id": run_id,
                    "message": _failure_message(run_id, [failure]),
                }
            self._save()
            await self.resume_notification()
            return self.snapshot()


_parse_datetime = parse_datetime


def _failure_message(run_id: str, failures: list[Any]) -> str:
    return (
        f"sweep-run:{run_id} Daily learn sweep failed ({len(failures)} failures). "
        "See attached notes."
    )[:299]
