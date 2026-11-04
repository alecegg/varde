"""Deterministic mailman relay loop for the runner service."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never, Protocol

from varde_data.config import load_data_config
from varde_data.errors import Locked
from varde_data.open import open_data
from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import NewMessage
from varde_data.relay import RelayService, Stopped
from varde_data.role_inbox import select_role_inbox
from varde_data.views.msg_status import runner_relay_alive
from varde_data.views.relay_liveness import HEARTBEAT_SECONDS

from varde_runner.relay_cli import (
    RelayCLI,
    RelayCommandError,
    parse_relay_mode,
)
from varde_runner.relay_cli import (
    command_error as _command_error,
)
from varde_runner.relay_prune import prune_legacy_mailman_state
from varde_runner.supervisor import SendOutcome
from varde_runner.varde_cli import VardeCLI
from varde_runner.wake import wake_agent_id

logger = logging.getLogger(__name__)

PLAN_REFRESH_TIMEOUT = 120.0
STALL_TIMEOUT = 30.0
FIRST_PLAN_REFRESH_TIMEOUT = 1.0
IDLE_STATUS_TIMEOUT = 20.0
WAIT_PROGRESS_STALE_INTERVALS = 2


def command_error(
    code: int, stdout: str, stderr: str, args: tuple[str, ...]
) -> RelayCommandError:
    """Keep the historical import path for the compatibility adapter error."""
    return _command_error(code, stdout, stderr, args)


def _raise(error: Exception) -> Never:
    raise error


class RelayCLIProtocol(Protocol):
    async def status(self) -> dict[str, Any]: ...

    async def bindings(self) -> list[dict[str, Any]]: ...

    async def issue_and_bind(self, session_id: str, /) -> str: ...

    async def issue_and_bind_superseding(self, session_id: str, /) -> str: ...

    async def wait(self, identity: str, /) -> dict[str, Any]: ...

    async def confirm(
        self,
        action_id: str,
        result: str,
        evidence: str,
        identity: str,
        /,
        *,
        harness: str,
    ) -> None: ...

    async def renew(self, action_id: str, /) -> dict[str, Any]: ...

    async def end(self, identity: str, /) -> None: ...

    async def unbind(self, session_id: str, /) -> None: ...


def decide(
    action: dict[str, Any], status: str | dict[str, Any] | Exception
) -> tuple[str, str] | str:
    """Choose the relay result and evidence for an action."""
    wake = action.get("wake") or {}
    if not wake_agent_id(wake):
        return "failed", "no-send"
    archived = False
    if isinstance(status, dict):
        archived = bool(status.get("archived"))
        status = status.get("status", "unknown")
    if isinstance(status, Exception):
        if _agent_not_found(status):
            return "target-gone", "observed-result"
        return "failed", "no-send"
    if archived and status not in {"idle", "closed"}:
        return "skipped-busy", "observed-result"
    if status in {"error", "unknown", None}:
        return "failed", "no-send"
    if status == "not-found":
        return "target-gone", "observed-result"
    if status != "idle" and not (archived and status == "closed"):
        return "skipped-busy", "observed-result"
    return "send"


def urgent_delivery_action(capabilities: Any, *, urgent: bool, busy: bool) -> str:
    """Choose send, steer, interrupt, or queue from urgency and adapter support."""
    if not busy:
        return "send"
    if not urgent:
        return "skip"
    if getattr(capabilities, "steer", False):
        return "steer"
    if getattr(capabilities, "interrupt", False):
        return "interrupt"
    return "queued"


def result_for_send_error(exc: Exception) -> tuple[str, str]:
    if _agent_not_found(exc):
        return "target-gone", "observed-result"
    return "failed", "observed-result"


def _relay_send_result(
    outcome: SendOutcome, *, urgent: bool = False
) -> tuple[str, str]:
    if outcome == SendOutcome.QUEUED:
        return "pushed", "queued" if urgent else "successful-send"
    if outcome == SendOutcome.SKIPPED_BUSY:
        return "skipped-busy", "observed-result"
    if outcome == SendOutcome.NOT_FOUND:
        return "target-gone", "observed-result"
    return "failed", "observed-result"


def _agent_not_found(exc: Exception) -> bool:
    message = str(exc).lower()
    return "agent not found" in message or "agent session was not found" in message


def _is_stalled_plan(plan: Any, stale_after: timedelta, now: datetime) -> bool:
    if not isinstance(plan, dict) or not plan.get("idle_no_handback"):
        return False
    assigned_to = plan.get("assigned_to")
    plan_id = plan.get("id")
    newest_activity = plan.get("newest_activity")
    done, total = plan.get("done"), plan.get("total")
    awaiting_user = plan.get("awaiting_user")
    activity_old_enough = (
        isinstance(newest_activity, (int, float))
        and now.timestamp() - newest_activity >= stale_after.total_seconds()
    )
    return (
        isinstance(assigned_to, str)
        and bool(assigned_to)
        and isinstance(plan_id, str)
        and activity_old_enough
        and awaiting_user is None
        and isinstance(done, int)
        and isinstance(total, int)
        and done < total
        and stale_after.total_seconds() > 0
    )


class RelayWaitStopped(Exception):
    """Relay wait observed its stop event outside task cancellation."""


class DataRelay:
    """Async adapter over the blocking repository and RelayService APIs."""

    def __init__(
        self,
        cwd: Path,
        *,
        supervisor: Any = None,
        stale_after: timedelta = timedelta(minutes=20),
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        plan_watch: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.cwd = cwd.expanduser().resolve()
        data = open_data(self.cwd, load_data_config())
        self.addresses = data.addresses
        self.messages = data.messages
        self.role_inbox = select_role_inbox(self.cwd)
        self.now = now or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.service = RelayService(
            self.addresses,
            self.messages,
            role_inbox=self.role_inbox,
            now=self.now,
            monotonic=self.monotonic,
        )
        self.supervisor = supervisor
        self.stale_after = stale_after
        self.plan_watch = plan_watch or VardeCLI(cwd=self.cwd).read_plan_watch
        self.stop_event = threading.Event()
        self.plans: dict[str, Any] = {}
        self._plan_refresh: asyncio.Task[None] | None = None
        self._stall_offset = 0

    async def bindings(self) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self.addresses.list_bindings)
        return [
            {
                "address": row.address,
                "session_id": row.session_id,
                "harness": row.harness,
                "bound_at": row.bound_at.isoformat(),
                "last_seen": row.last_seen.isoformat(),
                "token_id": row.token_id,
                **row.extra,
            }
            for row in rows
        ]

    async def status(self) -> dict[str, Any]:
        snapshot = await asyncio.to_thread(self.addresses.relay_snapshot)
        now = datetime.now(UTC)
        mailmen = [
            {
                "id": token,
                "alive": await asyncio.to_thread(
                    self.addresses.mailman_alive, token, now
                ),
            }
            for token in snapshot.mailman_started
        ]
        current = await asyncio.to_thread(self.addresses.current_token, "mailman")
        relay_alive = runner_relay_alive(
            {
                "current_mailman": snapshot.current_mailman,
                "events": [dict(event) for event in snapshot.events],
            },
            now,
        )
        return {
            "runner_relay": "up" if relay_alive else "down",
            "mailman": "alive"
            if any(row["id"] == current and row["alive"] for row in mailmen)
            else "dead"
            if current
            else "none",
            "mailmen": mailmen,
        }

    async def issue_and_bind(self, session_id: str) -> str:
        return await self._issue_and_bind(session_id, False)

    async def issue_and_bind_superseding(self, session_id: str) -> str:
        return await self._issue_and_bind(session_id, True)

    async def _issue_and_bind(self, session_id: str, supersede: bool) -> str:
        now = datetime.now(UTC)
        marker = await asyncio.to_thread(
            self.addresses.issue,
            "mailman",
            supersede=supersede,
            now=now,
            issuer="runner",
        )
        redeemed = await asyncio.to_thread(
            self.addresses.redeem,
            marker,
            session_id,
            "codex",
            ReaderContext(cwd=str(self.cwd)),
            now=datetime.now(UTC),
        )
        if not redeemed:
            raise RuntimeError("mailman binding was not created")
        binding = await asyncio.to_thread(self.addresses.current_binding, "mailman")
        if binding is None or binding.session_id != session_id:
            raise RuntimeError("mailman binding was not created")
        return binding.token_id

    async def wait(self, identity: str) -> dict[str, Any]:
        stop_event = threading.Event()
        heartbeat_stop = threading.Event()
        progress_lock = threading.Lock()
        last_progress = [self.monotonic()]
        self.stop_event = stop_event
        try:
            refresh = self._start_plan_refresh()
            if not self.plans:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(refresh), FIRST_PLAN_REFRESH_TIMEOUT
                    )
            timeout = self._wait_timeout(self.plans)
            heartbeat = threading.Thread(
                target=self._heartbeat_while_waiting,
                args=(identity, timeout, heartbeat_stop, last_progress, progress_lock),
                name="varde-relay-heartbeat",
                daemon=True,
            )
            heartbeat.start()
            try:
                return await asyncio.to_thread(
                    self.service.wait,
                    identity,
                    timeout,
                    stop=stop_event.is_set,
                    poll=lambda delay: self._poll_with_progress(
                        delay, last_progress, progress_lock
                    ),
                )
            finally:
                heartbeat_stop.set()
                await asyncio.to_thread(heartbeat.join, HEARTBEAT_SECONDS + 1)
        except Stopped as exc:
            raise RelayWaitStopped from exc
        except asyncio.CancelledError:
            stop_event.set()
            raise

    def _heartbeat_while_waiting(
        self,
        identity: str,
        timeout: float,
        stop: threading.Event,
        last_progress: list[float],
        progress_lock: threading.Lock,
    ) -> None:
        deadline = self.monotonic() + timeout + HEARTBEAT_SECONDS
        expect_return_by = self.now() + timedelta(seconds=timeout)
        while not stop.wait(HEARTBEAT_SECONDS):
            monotonic_now = self.monotonic()
            with progress_lock:
                progress_age = monotonic_now - last_progress[0]
            if monotonic_now >= deadline or progress_age >= (
                WAIT_PROGRESS_STALE_INTERVALS * HEARTBEAT_SECONDS
            ):
                return
            now = self.now()
            try:
                if not self.addresses.heartbeat_if_waiting(
                    identity,
                    now,
                    instance_id=self.service.instance_id,
                    expect_return_by=expect_return_by,
                ):
                    return
            except Exception:
                logger.warning("relay waiting heartbeat failed", exc_info=True)

    def _poll_with_progress(
        self,
        delay: float,
        last_progress: list[float],
        progress_lock: threading.Lock,
    ) -> None:
        with progress_lock:
            last_progress[0] = self.monotonic()
        self.service.sleep(delay)

    def runner_relay_alive(self) -> bool:
        snapshot = self.addresses.relay_snapshot()
        return runner_relay_alive(
            {
                "current_mailman": snapshot.current_mailman,
                "events": [dict(event) for event in snapshot.events],
            },
            self.now(),
        )

    def _start_plan_refresh(self) -> asyncio.Task[None]:
        """Refresh plans and stall notices beside the wake wait, never before it."""
        if self._plan_refresh is None or self._plan_refresh.done():
            self._plan_refresh = asyncio.create_task(self._refresh_plans())
        return self._plan_refresh

    def cancel_plan_refresh(self) -> None:
        if self._plan_refresh is not None:
            self._plan_refresh.cancel()

    async def _refresh_plans(self) -> None:
        try:
            self.plans = await asyncio.wait_for(
                asyncio.to_thread(self.plan_watch, self._stale_arg()),
                PLAN_REFRESH_TIMEOUT,
            )
            await asyncio.wait_for(self._emit_stalls(self.plans), STALL_TIMEOUT)
        except Exception:  # plan reads must not stop mail delivery
            logger.warning("relay plan refresh failed", exc_info=True)

    def _stale_arg(self) -> str:
        seconds = max(1, int(self.stale_after.total_seconds()))
        return f"{seconds}s"

    def _wait_timeout(self, snapshot: dict[str, Any]) -> float:
        timeout = 60.0
        now = self.now()
        plans = snapshot.get("plans", [])
        start = self._stall_offset % max(len(plans), 1)
        ordered_plans = [*plans[start:], *plans[:start]]
        self._stall_offset = (start + 1) % max(len(plans), 1)
        for plan in ordered_plans:
            if not isinstance(plan, dict) or plan.get("stalled"):
                continue
            activity = plan.get("newest_activity")
            assigned_to = plan.get("assigned_to")
            done, total = plan.get("done"), plan.get("total")
            if (
                not isinstance(activity, (int, float))
                or not isinstance(assigned_to, str)
                or plan.get("state") != "active"
            ):
                continue
            if not isinstance(done, int) or not isinstance(total, int) or done >= total:
                continue
            due = datetime.fromtimestamp(activity, UTC) + self.stale_after
            remaining = (due - now).total_seconds()
            if remaining > 0:
                timeout = min(timeout, remaining)
        return max(0.05, timeout)

    async def _emit_stalls(self, snapshot: dict[str, Any]) -> None:
        if self.supervisor is None:
            return
        bindings = await asyncio.to_thread(self.addresses.list_bindings)
        rows = {row.address: row for row in bindings}
        existing = await asyncio.to_thread(self.messages.read_all)
        sent_subjects = {
            message.text.split(" ", 2)[1].rstrip(":")
            for message in existing.records
            if message.from_ == "runner"
            and message.to == "main"
            and message.text.startswith("Stall ")
        }
        for plan in snapshot.get("plans", []):
            if not _is_stalled_plan(plan, self.stale_after, self.now()):
                continue
            owner = plan["assigned_to"]
            binding = rows.get(owner)
            if binding is None:
                continue
            wake = binding.extra.get("wake_context", {})
            agent_id = wake_agent_id(wake)
            if not agent_id:
                continue
            try:
                status = await asyncio.wait_for(
                    self.supervisor.target_idle_status(
                        agent_id, wake.get("harness", binding.harness)
                    ),
                    IDLE_STATUS_TIMEOUT,
                )
            except TimeoutError:
                continue
            if status != "idle":
                continue
            subject = f"{plan['id']}@{int(plan['newest_activity'])}"
            if subject in sent_subjects:
                continue
            detail = str(plan.get("detail", "open work is idle"))
            await asyncio.to_thread(
                self.messages.append,
                NewMessage("runner", "main", "blocked", f"Stall {subject}: {detail}"),
            )
            sent_subjects.add(subject)

    async def confirm(
        self,
        action_id: str,
        result: str,
        evidence: str,
        identity: str,
        *,
        harness: str,
    ) -> None:
        await asyncio.to_thread(
            self.service.confirm,
            action_id,
            result,
            session=identity,
            harness=harness if harness in {"claude", "codex"} else "unknown",
            reason=evidence,
        )

    async def renew(self, action_id: str) -> dict[str, Any]:
        renewed = await asyncio.to_thread(self.service.renew, action_id)
        return {"status": "renewed" if renewed else "expired"}

    async def end(self, identity: str) -> None:
        await asyncio.to_thread(self.service.end, identity)

    async def unbind(self, session_id: str) -> None:
        await asyncio.to_thread(self.addresses.unbind, session_id, datetime.now(UTC))

    async def refusal_reason(self) -> str | None:
        event = await asyncio.to_thread(self.addresses.last_refusal, "mailman")
        return str(event.details.get("reason", "refused")) if event else None


class RelayWorker:
    def __init__(
        self,
        cli: RelayCLIProtocol | None,
        supervisor: Any,
        *,
        sleep=asyncio.sleep,
        plan_watch: Callable[[str], dict[str, Any]] | None = None,
        manager_wake: (
            Callable[[dict[str, Any]], Awaitable[tuple[str, str]]] | None
        ) = None,
    ):
        self.cli = cli
        self.supervisor = supervisor
        self.store = getattr(supervisor, "store", None)
        self.sleep = sleep
        self.plan_watch = plan_watch
        self.manager_wake = manager_wake
        self.identity: str | None = None
        self.session_id: str | None = None
        self.state = "starting"
        self.started_at = datetime.now(UTC).isoformat()
        self.last_wait = {"actions": 0, "deferred": 0}
        self.last_plan: dict[str, Any] | None = None
        self.last_delivery: dict[str, Any] | None = None
        self.failures: list[dict[str, str]] = []
        self.last_error: str | None = None
        self._confirmed: set[str] = set()
        self._confirmed_order: deque[str] = deque()
        self._stop = False
        self.refusal: str | None = None
        self._successful_wait = False
        self._rearmed = False
        self.task: asyncio.Task[None] | None = None

    @property
    def command(self) -> RelayCLIProtocol:
        if self.cli is None:
            raise RuntimeError("RelayCLI has not been initialized")
        return self.cli

    def snapshot(self) -> dict[str, Any]:
        task_done = self.task.done() if self.task is not None else False
        task_exception = None
        if task_done and self.task is not None and not self.task.cancelled():
            error = self.task.exception()
            task_exception = str(error) if error else None
        snapshot = {
            "next_deadline": self.store.earliest_deadline() if self.store else None,
            "state": self.state,
            "identity": self.identity,
            "queue": dict(self.last_wait),
            "last_plan": self.last_plan,
            "last_delivery": self.last_delivery,
            "failures": self.failures[-20:],
            "last_error": self.last_error,
            "refusal": self.refusal,
            "started_at": self.started_at,
            "task_done": task_done,
            "task_exception": task_exception,
        }
        if isinstance(self.cli, DataRelay):
            alive = self.cli.runner_relay_alive()
            snapshot["relay_alive"] = alive
            if self.state == "waiting" and not alive:
                snapshot["state"] = "stale"
        return snapshot

    async def run(self) -> None:
        self.task = asyncio.current_task()
        delay = 30
        try:
            working = Path(os.environ.get("VARDE_WORKING_DIR", "."))
            try:
                result = await asyncio.to_thread(prune_legacy_mailman_state, working)
                if result["pruned"]:
                    logger.info(
                        "pruned legacy mailman generations: %s", result["pruned"]
                    )
            except Locked:
                logger.warning(
                    "legacy mailman generation prune skipped: relay state locked"
                )
            except OSError, ValueError, TypeError:
                logger.warning("legacy mailman generation prune failed", exc_info=True)
            mode = parse_relay_mode(os.environ.get("VARDE_RUNNER_RELAY")) or "data"
            while not self._stop:
                try:
                    if self.cli is None:
                        self.cli = (
                            RelayCLI()
                            if mode == "cli"
                            else await asyncio.to_thread(
                                DataRelay,
                                Path(os.environ.get("VARDE_WORKING_DIR", ".")),
                                supervisor=self.supervisor,
                                plan_watch=self.plan_watch,
                            )
                        )
                    if self.identity is None:
                        if not await self._start_binding():
                            return
                        self._successful_wait = False
                    identity = self.identity
                    if identity is None:
                        _raise(RuntimeError("relay identity was not created"))
                    if not self._rearmed:
                        await self._rearm_wakes()
                    self.state = "waiting"
                    response = await self.command.wait(identity)
                    self._successful_wait = True
                    if await self._process_response(response):
                        return
                    delay = 30
                except asyncio.CancelledError:
                    raise
                except RelayWaitStopped:
                    self.state = "stopped"
                    return
                except Exception as exc:  # noqa: BLE001
                    stop, delay = await self._recover(exc, delay)
                    if stop:
                        return
        finally:
            if isinstance(self.cli, DataRelay):
                self.cli.stop_event.set()
                self.cli.cancel_plan_refresh()
            try:
                await asyncio.wait_for(self._release(), timeout=10)
            except TimeoutError:
                self._failure(RuntimeError("relay shutdown cleanup timed out"))
            if self.state not in {"refused", "stopped"}:
                self.state = "stopped"

    async def _release(self) -> None:
        identity = self.identity
        if identity:
            try:
                await self.command.end(identity)
            except Exception as exc:  # noqa: BLE001
                self._failure(exc)
        session_id = self.session_id
        if session_id:
            try:
                await self.command.unbind(session_id)
            except Exception as exc:  # noqa: BLE001
                self._failure(exc)

    async def _refusal_reason(self) -> str | None:
        if isinstance(self.cli, DataRelay):
            return await self.cli.refusal_reason()
        if isinstance(self.cli, RelayCLI):
            data = open_data(self.cli.cwd, load_data_config())
            event = await asyncio.to_thread(data.addresses.last_refusal, "mailman")
            return str(event.details.get("reason", "refused")) if event else None
        return None

    async def _start_binding(self) -> bool:
        bindings = await self.command.bindings()
        report = await self.command.status()
        holder = next(
            (item for item in bindings if item.get("address") == "mailman"), None
        )
        mailmen = report.get("mailmen")
        if isinstance(mailmen, list):
            holder_alive = bool(holder) and any(
                item.get("alive") and item.get("id") == holder.get("token_id")
                for item in mailmen
                if isinstance(item, dict)
            )
        else:
            holder_alive = bool(holder) and report.get("runner_relay") == "up"
        runner_holder = bool(
            holder and str(holder.get("session_id", "")).startswith("runner-")
        )
        if holder is not None and holder_alive and not runner_holder:
            self.refusal = f"mailman is held by {holder.get('session_id', 'unknown')}"
            self.last_error = self.refusal
            logger.warning("relay startup refused: %s", self.refusal)
            self.state = "refused"
            return False
        self.refusal = None
        session_id = f"runner-{uuid.uuid4().hex}"
        try:
            if runner_holder:
                identity = await self.command.issue_and_bind_superseding(session_id)
            else:
                identity = await self.command.issue_and_bind(session_id)
        except Exception as exc:
            reason = await self._refusal_reason()
            self.refusal = f"{exc}{f' ({reason})' if reason else ''}"
            logger.warning("relay bind refused: %s", self.refusal)
            raise RuntimeError(self.refusal) from exc
        self.identity = identity
        self.session_id = session_id
        self.last_error = None
        self._rearmed = False
        logger.info("relay started: mode=%s", type(self.cli).__name__)
        return True

    def _failure(self, exc: Exception) -> None:
        self.last_error = str(exc)
        self.failures.append({"error": str(exc), "at": datetime.now(UTC).isoformat()})
        self.failures = self.failures[-20:]

    async def _recover(self, exc: Exception, delay: int) -> tuple[bool, int]:
        self._failure(exc)
        if self._successful_wait and (
            (isinstance(exc, RelayCommandError) and exc.returncode == 64)
            or "superseded" in str(exc).lower()
        ):
            self.state = "stopped"
            return True, delay
        self.state = "backoff"
        await self.sleep(delay)
        return False, min(300, delay * 2)

    async def _process_response(self, response: dict[str, Any]) -> bool:
        if response.get("status") == "superseded":
            self.state = "stopped"
            return True
        actions = response.get("actions", [])
        self.last_wait = {
            "actions": len(actions),
            "deferred": len(response.get("deferred", [])),
        }
        self.last_plan = {
            "status": response.get("status"),
            "actions": [
                {
                    "action_id": action.get("action_id"),
                    "message_ids": action.get("message_ids", []),
                    "wake": action.get("wake"),
                }
                for action in actions
            ],
            "deferred": len(response.get("deferred", [])),
        }
        logger.info(
            "relay planned: actions=%d deferred=%d",
            self.last_wait["actions"],
            self.last_wait["deferred"],
        )
        for action in actions:
            await self._handle(action)
        if (response.get("mailman") or {}).get("recreate"):
            old_identity = self.identity
            self.identity = None
            if old_identity:
                await self.command.end(old_identity)
        self.state = "waiting"
        return False

    async def _handle(self, action: dict[str, Any]) -> None:
        action_id = str(action.get("action_id", ""))
        if not action_id or action_id in self._confirmed:
            return
        self._store_wake(action)
        self.state = "delivering"
        operation = asyncio.create_task(self._deliver_and_confirm(action, action_id))
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _deliver_and_confirm(
        self, action: dict[str, Any], action_id: str
    ) -> None:
        if self._already_pushed(action):
            outcome = ("pushed", "successful-send")
        else:
            outcome = await self.deliver(action)
        if outcome is None:
            self._resolve_wake(action, "expired")
            return
        result, evidence = outcome
        self._resolve_wake(action, result)
        wake = action.get("wake") or {}
        harness = wake.get("harness") if isinstance(wake, dict) else None
        if not isinstance(harness, str) or not harness:
            binding = action.get("binding") or {}
            harness = str(binding.get("harness") or "unknown")
        confirmation = self.command.confirm(
            action_id, result, evidence, self.identity or "", harness=harness
        )
        confirm_task = asyncio.ensure_future(confirmation)
        try:
            await asyncio.shield(confirm_task)
        except asyncio.CancelledError:
            await confirm_task
            self._record_confirmation(action, action_id, result)
            raise
        self._record_confirmation(action, action_id, result)

    def _store_wake(self, action: dict[str, Any]) -> None:
        if self.store is None:
            return
        action_id = str(action.get("action_id", ""))
        agent_id = wake_agent_id(action.get("wake") or {})
        if not action_id or not agent_id:
            return
        self.store.create_wait(
            f"wake:{action_id}",
            agent_id,
            "wake",
            action.get("expires_at"),
            action,
        )
        self.store.rearm_wake(f"wake:{action_id}")

    def _already_pushed(self, action: dict[str, Any]) -> bool:
        action_id = str(action.get("action_id", ""))
        if self.store is None:
            return False
        wait = self.store.get_wait(f"wake:{action_id}")
        if (
            wait
            and wait.get("state") == "resolved"
            and wait.get("decision") == "pushed"
        ):
            return True
        message_ids = set(action.get("message_ids", []))
        return bool(message_ids) and message_ids <= self.store.pushed_wake_message_ids(
            message_ids
        )

    def _resolve_wake(self, action: dict[str, Any], decision: str) -> None:
        if self.store is None:
            return
        action_id = str(action.get("action_id", ""))
        if decision in {"pushed", "target-gone", "failed"} and action_id:
            self.store.resolve_wait(f"wake:{action_id}", "resolved", decision)
        elif decision == "expired" and action_id:
            self.store.resolve_wait(f"wake:{action_id}", "expired", decision)

    async def _rearm_wakes(self) -> None:
        if self.store is None:
            self._rearmed = True
            return
        for wait in self.store.pending_waits():
            if wait.get("kind") != "wake":
                continue
            action = wait.get("payload")
            if not isinstance(action, dict):
                self.store.resolve_wait(wait["wait_id"], "expired", "invalid_payload")
                continue
            action_id = str(action.get("action_id", ""))
            if not action_id:
                self.store.resolve_wait(wait["wait_id"], "expired", "invalid_action")
                continue
            deadline = wait.get("deadline")
            if isinstance(deadline, str):
                expires_at = datetime.fromisoformat(deadline)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= datetime.now(UTC):
                    self.store.resolve_wait(wait["wait_id"], "expired", "lease_expired")
                    continue
            renewed = await self.command.renew(action_id)
            if renewed.get("status") == "expired":
                self.store.resolve_wait(wait["wait_id"], "expired", "lease_expired")
                continue
            await self._handle(action)
        # Pushed-but-unconfirmed leases converge on workflow re-offer via
        # message-id dedupe.
        self._rearmed = True

    async def deliver(  # noqa: PLR0911
        self, action: dict[str, Any]
    ) -> tuple[str, str] | None:
        """Return a decided outcome; None means the lease must be left alone."""
        action_id = str(action.get("action_id", ""))
        renewed = await self.command.renew(action_id)
        if renewed.get("status") == "expired":
            return None
        if action.get("address") == "manager" and self.manager_wake is not None:
            return await self.manager_wake(action)
        wake = action.get("wake") or {}
        agent_id = wake_agent_id(wake)
        if not agent_id:
            return "failed", "no-send"
        harness = wake.get("harness")
        try:
            status = await self._idle_status(agent_id, harness)
            base_decision = decide(action, status)
            busy = (
                isinstance(base_decision, tuple) and base_decision[0] == "skipped-busy"
            )
            if not busy and base_decision != "send":
                return (
                    base_decision
                    if isinstance(base_decision, tuple)
                    else ("failed", "no-send")
                )
            registry = getattr(self.supervisor, "registry", None)
            try:
                capabilities = registry.capabilities(harness) if registry else None
            except KeyError, ValueError:
                capabilities = None
            delivery = urgent_delivery_action(
                capabilities, urgent=bool(action.get("urgent")), busy=busy
            )
            if delivery == "skip":
                return "skipped-busy", "observed-result"
            if delivery == "queued":
                return "skipped-busy", "queued"
            if delivery == "steer":
                outcome = await asyncio.wait_for(
                    self.supervisor.send(
                        agent_id,
                        action.get("prompt", ""),
                        harness,
                        request_id=action_id,
                    ),
                    30,
                )
                if outcome != SendOutcome.SENT:
                    return _relay_send_result(outcome, urgent=True)
                return "pushed", "steer"
            if delivery == "interrupt":
                outcome = await asyncio.wait_for(
                    self.supervisor.send_with_interrupt(
                        agent_id,
                        action.get("prompt", ""),
                        harness,
                        request_id=action_id,
                    ),
                    30,
                )
                if outcome != SendOutcome.SENT:
                    return _relay_send_result(outcome, urgent=True)
                return "pushed", "interrupt"
            decision = base_decision
            if decision != "send":
                logger.info("relay send skipped: decision=%s", decision)
                return (
                    decision if isinstance(decision, tuple) else ("failed", "no-send")
                )
            logger.info("relay send started: target_present=true")
            outcome = await asyncio.wait_for(
                self.supervisor.send(
                    agent_id,
                    action.get("prompt", ""),
                    harness,
                    request_id=action_id,
                ),
                30,
            )
        except Exception as exc:  # noqa: BLE001
            return result_for_send_error(exc)
        if outcome != SendOutcome.SENT:
            if outcome == SendOutcome.QUEUED:
                logger.info("relay send accepted into takeover queue")
            else:
                logger.info("relay send finished: outcome=%s", outcome.value)
            return _relay_send_result(outcome, urgent=bool(action.get("urgent")))
        logger.info("relay send finished: outcome=sent")
        return "pushed", "steer" if busy and action.get("urgent") else "successful-send"

    async def _idle_status(self, agent_id: str, harness: Any) -> Any:
        try:
            return await asyncio.wait_for(
                self.supervisor.target_idle_status(agent_id, harness),
                IDLE_STATUS_TIMEOUT,
            )
        except TimeoutError as exc:
            return exc

    def _record_confirmation(
        self, action: dict[str, Any], action_id: str, result: str
    ) -> None:
        self._confirmed.add(action_id)
        self._confirmed_order.append(action_id)
        if result == "skipped-busy":
            self._confirmed.discard(action_id)
            self._confirmed_order.remove(action_id)
        while len(self._confirmed) > 1024:
            self._confirmed.discard(self._confirmed_order.popleft())
        self.last_delivery = {
            "message_ids": action.get("message_ids", []),
            "result": result,
            "at": datetime.now(UTC).isoformat(),
        }
