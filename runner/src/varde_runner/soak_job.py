"""Daily runner job that invokes the mail reliability soak through the CLI."""

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


def require_soak_exit(code: int, stdout: str, stderr: str) -> None:
    if code in (0, 1):
        return
    raise RuntimeError(stderr.strip() or stdout.strip() or f"soak exited {code}")


def parse_soak_output(stdout: str) -> dict[str, Any]:
    """Parse the report JSON printed by ``varde msg soak --json``."""
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise TypeError("mail soak output must be a JSON object")
    data = value.get("data", value)
    if not isinstance(data, dict):
        raise TypeError("mail soak output data must be a JSON object")
    for key in (
        "date",
        "window_days",
        "criteria",
        "active_orchestrators",
        "all_ok",
        "days_ok_streak",
    ):
        if key not in data:
            raise TypeError(f"mail soak output is missing {key}")
    if not isinstance(data["date"], str) or not isinstance(data["criteria"], list):
        raise TypeError("mail soak output has invalid report fields")
    if not isinstance(data["all_ok"], bool):
        raise TypeError("mail soak all_ok must be a boolean")
    return data


def _scheduled_time(value: str) -> time:
    return parse_scheduled_time(value, "mail soak time must use 24-hour HH:MM format")


def configured_schedule_time(value: str) -> str:
    return _configured_schedule_time(
        value,
        error_message="mail soak time must use 24-hour HH:MM format",
        environment_name="VARDE_MAIL_SOAK_TIME",
        default="03:15",
        logger=logger,
    )


def next_run_at(
    now: datetime, schedule_time: str, last_run_at: datetime | None
) -> datetime:
    return _shared_next_run_at(
        now,
        schedule_time,
        last_run_at,
        past_run_result=lambda current, today: max(today, current),
        error_message="mail soak time must use 24-hour HH:MM format",
    )


class SoakClock(DailyJobClock):
    pass


class SoakJob(DailyJob):
    """Persistent daily report runner with an idempotent failure notification."""

    def __init__(  # noqa: PLR0913 - expose the shared DailyJob control hooks
        self,
        state_path: Path,
        *,
        execute: Callable[[], Any],
        notify: Callable[[str, str], Any] | None = None,
        messages: Callable[[], Any] | None = None,
        schedule_time: str = "03:15",
        clock: SoakClock | None = None,
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
                clock=clock or SoakClock(),
                empty_state={
                    "last_run_at": None,
                    "report": None,
                    "error": None,
                    "state": "idle",
                    "notification_pending": None,
                    "notification_sent": [],
                },
                temporary_prefix=".mail-soak-job-",
                notification_prefix="mail-soak-run:",
                logger=logger,
                notification_name="mail soak",
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
            "report": self.state.get("report"),
            "error": self.state.get("error"),
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
            self.state.update({"state": "running", "error": None})
            self._save()
            run_id = self.clock.now().astimezone(UTC).isoformat()
            try:
                code, stdout, stderr = await self.execute()
                require_soak_exit(code, stdout, stderr)
                report = parse_soak_output(stdout)
                self.state.update(
                    {
                        "last_run_at": self.clock.now().astimezone(UTC).isoformat(),
                        "report": report,
                        "error": None,
                        "state": "succeeded",
                    }
                )
            except Exception as error:  # noqa: BLE001 - persist subprocess and parse failures
                message = str(error)[:500]
                self.state.update(
                    {
                        "last_run_at": self.clock.now().astimezone(UTC).isoformat(),
                        "error": message,
                        "state": "failed",
                    }
                )
                text = f"mail-soak-run:{run_id} Daily mail soak failed: {message}"
                self.state["notification_pending"] = {
                    "run_id": run_id,
                    "message": text[:299],
                }
            self._save()
            await self.resume_notification()
            return self.snapshot()

    async def run(self) -> None:
        while True:
            try:
                await self.resume_notification()
                await self._run_scheduled_iteration()
            except Exception:
                logger.exception("Mail soak job failed; retrying in 60 seconds")
                await self.clock.sleep(60)


_parse_datetime = parse_datetime
