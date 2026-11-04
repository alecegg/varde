"""Shared scheduling and persistence primitives for daily runner jobs."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

from varde_core.utc import as_utc, parse_datetime, utc_day

PAUSED_RECHECK_SECONDS = 60


def parse_scheduled_time(value: str, error_message: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour, minute, tzinfo=UTC)
    except (ValueError, TypeError) as error:
        raise ValueError(error_message) from error


def configured_schedule_time(
    value: str,
    *,
    error_message: str,
    environment_name: str,
    default: str,
    logger: logging.Logger,
) -> str:
    try:
        parse_scheduled_time(value, error_message)
    except ValueError:
        logger.warning("Invalid %s %r; using %s UTC", environment_name, value, default)
        return default
    return value


def next_run_at(
    now: datetime,
    schedule_time: str,
    last_run_at: datetime | None,
    *,
    past_run_result: Callable[[datetime, datetime], datetime],
    error_message: str,
) -> datetime:
    now = as_utc(now)
    scheduled = parse_scheduled_time(schedule_time, error_message)
    today = datetime.combine(now.date(), scheduled)
    if last_run_at is not None:
        last_run_date = utc_day(last_run_at)
        if last_run_date == now.date():
            return today + timedelta(days=1)
        if last_run_date < now.date():
            return past_run_result(now, today)
    return max(today, now)


@dataclass(frozen=True)
class DailyJobClock:
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleep: Callable[[float], Any] = asyncio.sleep


@dataclass(frozen=True)
class DailyJobConfig:
    state_path: Path
    execute: Callable[[], Any]
    notify: Callable[[str, str], Any] | None
    messages: Callable[[], Any] | None
    schedule_time: str
    clock: DailyJobClock
    empty_state: dict[str, Any]
    temporary_prefix: str
    notification_prefix: str
    logger: logging.Logger
    notification_name: str
    enabled_check: Callable[[], Any] | None = None
    run_recorder: Callable[[str, dict[str, Any]], Any] | None = None
    run_started: Callable[[str], Any] | None = None
    run_finished: Callable[[Any, dict[str, Any], BaseException | None], Any] | None = (
        None
    )


class DailyJob:
    """Common state, notification, and scheduler loop for one daily job."""

    def __init__(self, config: DailyJobConfig) -> None:
        self.state_path = config.state_path
        self.execute = config.execute
        self.notify = config.notify
        self.messages = config.messages
        self.schedule_time = config.schedule_time
        self.clock = config.clock
        self.empty_state = config.empty_state
        self.temporary_prefix = config.temporary_prefix
        self.notification_prefix = config.notification_prefix
        self.logger = config.logger
        self.notification_name = config.notification_name
        self.enabled_check = config.enabled_check
        self.run_recorder = config.run_recorder
        self.run_started = config.run_started
        self.run_finished = config.run_finished
        self.lock = asyncio.Lock()
        self.state = self._read_state()

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            return dict(self.empty_state)
        if not isinstance(value, dict):
            return dict(self.empty_state)
        return {**self.empty_state, **value}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=self.temporary_prefix, dir=self.state_path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self.state, stream, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)

    async def resume_notification(self) -> None:
        pending = self.state.get("notification_pending")
        if not isinstance(pending, dict) or self.notify is None:
            return
        run_id, message = pending.get("run_id"), pending.get("message")
        if not isinstance(run_id, str) or not isinstance(message, str):
            return
        sent = self.state.get("notification_sent", [])
        if run_id in sent:
            self.state["notification_pending"] = None
            self._save()
            return
        if self.messages is not None:
            existing = self.messages()
            if inspect.isawaitable(existing):
                existing = await existing
            if any(
                item.get("kind") == "info-failure"
                and f"{self.notification_prefix}{run_id}" in str(item.get("text", ""))
                for item in existing
                if isinstance(item, dict)
            ):
                self._mark_notified(run_id)
                return
        try:
            result = self.notify(run_id, message)
            if inspect.isawaitable(result):
                await result
        except Exception as error:  # noqa: BLE001 - retain pending notice and keep scheduler alive
            self.logger.warning(
                "Could not deliver %s failure notice %s: %s",
                self.notification_name,
                run_id,
                error,
            )
            return
        self._mark_notified(run_id)

    def _mark_notified(self, run_id: str) -> None:
        sent = self.state.setdefault("notification_sent", [])
        if run_id not in sent:
            sent.append(run_id)
            self.state["notification_sent"] = sent[-100:]
        self.state["notification_pending"] = None
        self._save()

    async def _run_scheduled_iteration(self) -> None:
        if not await self._is_enabled():
            await self.clock.sleep(PAUSED_RECHECK_SECONDS)
            return
        next_time = self._next_run_at(
            self.clock.now(),
            self.schedule_time,
            parse_datetime(self.state.get("last_run_at")),
        )
        delay = max(0.0, (next_time - self.clock.now().astimezone(UTC)).total_seconds())
        if delay:
            await self.clock.sleep(delay)
            return
        if await self._is_enabled():
            await self._run_and_record("schedule")

    async def _is_enabled(self) -> bool:
        if self.enabled_check is None:
            return True
        enabled = self.enabled_check()
        if inspect.isawaitable(enabled):
            enabled = await enabled
        return bool(enabled)

    async def _run_and_record(self, trigger: str) -> dict[str, Any]:
        run_id = None
        if self.run_started is not None:
            run_id = self.run_started(trigger)
            if inspect.isawaitable(run_id):
                run_id = await run_id
        error = None
        snapshot: dict[str, Any] = {}
        try:
            snapshot = await self._execute_run()
        except BaseException as caught:
            error = caught
            raise
        else:
            return snapshot
        finally:
            if self.run_finished is not None and run_id is not None:
                finished = self.run_finished(run_id, snapshot, error)
                if inspect.isawaitable(finished):
                    await finished
            elif self.run_recorder is not None and error is None:
                recorded = self.run_recorder(trigger, snapshot)
                if inspect.isawaitable(recorded):
                    await recorded

    def _next_run_at(
        self, now: datetime, schedule_time: str, last_run: datetime | None
    ) -> datetime:
        raise NotImplementedError

    async def run_now(self) -> dict[str, Any]:
        raise NotImplementedError

    async def _execute_run(self) -> dict[str, Any]:
        raise NotImplementedError

    async def run(self) -> None:
        await self.resume_notification()
        while True:
            await self._run_scheduled_iteration()
