"""Daily runner job that invokes learn review through its CLI boundary."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime
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
DEFAULT_REVIEW_TIMEOUT_SECONDS = 900
REVIEW_TIMEOUT_ENV = "VARDE_LEARN_REVIEW_TIMEOUT_SECONDS"


def _raise_review_failure(stderr: str, stdout: str, code: int) -> None:
    from varde_core.redact import RedactConfig, Redactor

    message = stderr.strip() or stdout.strip() or f"review exited {code}"
    raise RuntimeError(Redactor(RedactConfig()).redact(message).text)


def configured_timeout_seconds(value: str | None) -> int:
    try:
        timeout = int(value) if value is not None else DEFAULT_REVIEW_TIMEOUT_SECONDS
    except ValueError:
        timeout = 0
    if timeout > 0:
        return timeout
    logger.warning(
        "Invalid %s %r; using %s seconds",
        REVIEW_TIMEOUT_ENV,
        value,
        DEFAULT_REVIEW_TIMEOUT_SECONDS,
    )
    return DEFAULT_REVIEW_TIMEOUT_SECONDS


async def execute_review_cli(
    *,
    budget_tokens: int,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
    spawn: Callable[..., Any] | None = None,
) -> tuple[int, str, str]:
    create_process = spawn or asyncio.create_subprocess_exec
    process = await create_process(
        "varde",
        "learn",
        "run",
        "--json",
        "--window",
        "since-last",
        "--budget-tokens",
        str(budget_tokens),
        cwd=cwd,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return (
            124,
            "",
            f"review timed out after {timeout_seconds} seconds",
        )
    except BaseException:
        process.kill()
        await process.wait()
        raise
    return (
        process.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


def configured_schedule_time(value: str) -> str:
    return _configured_schedule_time(
        value,
        error_message="review time must use 24-hour HH:MM format",
        environment_name="VARDE_LEARN_REVIEW_TIME",
        default="04:00",
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
        error_message="review time must use 24-hour HH:MM format",
    )


def parse_review_output(stdout: str) -> dict[str, Any]:
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise TypeError("review output must be a JSON object")
    data = value.get("data", value)
    if not isinstance(data, dict) or not isinstance(data.get("run_at"), str):
        raise TypeError("review output data must contain run_at")
    datetime.fromisoformat(data["run_at"])
    model_tokens = _optional_nonnegative_int(data.get("model_tokens"))
    cost_usd = _optional_nonnegative_number(data.get("cost_usd_estimate"))
    budget_tokens = _optional_positive_int(data.get("budget_tokens"))
    if data.get("model_tokens") is not None and model_tokens is None:
        raise ValueError("review model_tokens must be a non-negative integer")
    if data.get("cost_usd_estimate") is not None and cost_usd is None:
        raise ValueError("review cost_usd_estimate must be a non-negative number")
    if data.get("budget_tokens") is not None and budget_tokens is None:
        raise ValueError("review budget_tokens must be a positive integer")
    budget_exhausted = data.get("budget_exhausted", False)
    if not isinstance(budget_exhausted, bool):
        raise TypeError("review budget_exhausted must be a boolean")
    coverage = data.get("coverage")
    if coverage is not None:
        coverage = _coverage_snapshot(coverage)
    return {
        "last_run_at": data["run_at"],
        "model_tokens": model_tokens,
        "cost_usd": cost_usd,
        "budget_tokens": budget_tokens,
        "budget_exhausted": budget_exhausted,
        "stop_reason": data.get("stop_reason"),
        "stop_error": data.get("stop_error"),
        "coverage": coverage,
        "report_path": data.get("report_path"),
        "error": None,
        "state": "succeeded",
    }


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _optional_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _coverage_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("review coverage must be an object")
    count_keys = ("found", "analyzed", "skipped", "failed")
    counts = {key: _optional_nonnegative_int(value.get(key)) for key in count_keys}
    if any(count is None for count in counts.values()):
        raise ValueError("review coverage counts must be non-negative integers")
    by_harness = value.get("by_harness", {})
    if not isinstance(by_harness, dict):
        raise TypeError("review coverage by_harness must be an object")
    pending = _optional_nonnegative_int(value.get("pending", 0))
    if pending is None:
        raise ValueError("review coverage pending count must be non-negative")
    return {**counts, "pending": pending, "by_harness": by_harness}


class ReviewJob(DailyJob):
    """Persistent scheduled model-using learn review."""

    def __init__(
        self,
        state_path: Path,
        *,
        execute: Callable[[], Any],
        schedule_time: str = "04:00",
        clock: DailyJobClock | None = None,
        enabled_check: Callable[[], Any] | None = None,
        run_recorder: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        parse_scheduled_time(schedule_time, "review time must use 24-hour HH:MM format")
        super().__init__(
            DailyJobConfig(
                state_path=state_path,
                execute=execute,
                notify=None,
                messages=None,
                schedule_time=schedule_time,
                clock=clock or DailyJobClock(),
                empty_state={
                    "last_run_at": None,
                    "model_tokens": None,
                    "cost_usd": None,
                    "budget_tokens": None,
                    "budget_exhausted": False,
                    "coverage": None,
                    "state": "idle",
                },
                temporary_prefix=".review-job-",
                notification_prefix="review-run:",
                logger=logger,
                notification_name="review",
                enabled_check=enabled_check,
                run_recorder=run_recorder,
            )
        )

    async def _execute_run(self) -> dict[str, Any]:
        async with self.lock:
            self.state["state"] = "running"
            self._save()
            try:
                code, stdout, stderr = await self.execute()
                if code:
                    _raise_review_failure(stderr, stdout, code)
                self.state.update(parse_review_output(stdout))
            except Exception as error:  # noqa: BLE001 - persist CLI and parse failures
                self.state.update({"state": "failed", "error": str(error)[:500]})
            self._save()
            return self.snapshot()

    def _next_run_at(
        self, now: datetime, schedule_time: str, last_run: datetime | None
    ) -> datetime:
        return next_run_at(now, schedule_time, last_run)

    def snapshot(self) -> dict[str, Any]:
        snapshot = {
            key: self.state.get(key)
            for key in (
                "last_run_at",
                "model_tokens",
                "cost_usd",
                "budget_tokens",
                "budget_exhausted",
                "stop_reason",
                "stop_error",
                "coverage",
                "report_path",
                "error",
                "state",
            )
        }
        last_run = parse_datetime(self.state.get("last_run_at"))
        snapshot["next_run_at"] = next_run_at(
            self.clock.now(), self.schedule_time, last_run
        ).isoformat()
        return snapshot

    async def run_now(self) -> dict[str, Any]:
        return await self._run_and_record("manual")
