"""Persistent owner of plugin sessions, state, and recovery policy."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import secrets
import sys
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from varde_runner import slot_park
from varde_runner.agent_launch import data_root
from varde_runner.bot_permissions import Decision, decide_request
from varde_runner.bot_profile import BOT_ROLE, ProfileUnsupported, is_restricted
from varde_runner.bot_taint import is_bot_rooted
from varde_runner.clients import (
    SYSTEM_CLIENT_IDS,
    ClientRegistry,
    ClientRole,
    ObserverReadOnly,
    UnknownClient,
    WriterLeases,
)
from varde_runner.config import (
    KNOWN_HARNESSES,
    Model,
    config_path,
    default_config,
    load_config,
)
from varde_runner.decision_metrics import (
    classify_request_kind,
    plan_from_branch,
    redact_request_key,
)
from varde_runner.diagnostic import (
    append_startup_diagnostic,
    startup_diagnostic,
    startup_timeout_error,
)
from varde_runner.guard import evaluate as evaluate_guard
from varde_runner.guard_log import redact_prompt
from varde_runner.guard_policy import allowlist as guard_allowlist
from varde_runner.instance_cap import InstanceCapError, live_count, over_cap
from varde_runner.ipc import create_server_socket, serve_client
from varde_runner.liveness import (
    Liveness,
    derive_liveness,
    event_age_s,
    is_agent_output,
)
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import (
    InterruptiblePlugin,
    ResumeSettings,
    RunnerPlugin,
    UnsupportedCapability,
    accepts_settings,
    plugin_is_provider_limit_error,
)
from varde_runner.protocol import (
    resume as resume_plugin,
)
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.store import SessionStore
from varde_runner.waits import (
    approval_wait_id,
    is_expired,
    normalize_decision,
    response_for_wait,
)
from varde_runner.watch import WatchHub
from varde_runner.workitems import WorkItemStore

logger = logging.getLogger(__name__)


async def _send_plugin_prompt(
    plugin: RunnerPlugin,
    ref: SessionRef,
    prompt: str,
    request_id: str | None = None,
) -> None:
    send_with_id = getattr(plugin, "send_with_id", None)
    if request_id is not None and callable(send_with_id):
        await cast("Callable[[SessionRef, str, str], Awaitable[None]]", send_with_id)(
            ref, prompt, request_id
        )
        return
    await plugin.send(ref, prompt)


def _is_quiet_idle(
    session_status: str,
    status_event: Mapping[str, Any] | None,
    open_intents: list[dict[str, Any]],
) -> bool:
    # A crash before the plugin emits running is indistinguishable from quiet idleness.
    return (
        session_status != "error"
        and status_event is not None
        and status_event["payload"].get("status") == "idle"
        and not open_intents
    )


class SendOutcome(StrEnum):
    SENT = "sent"
    QUEUED = "queued"
    SKIPPED_BUSY = "skipped_busy"
    FAILED = "failed"
    FAILED_INTERRUPT = "failed_interrupt"
    NOT_FOUND = "not_found"


class Supervisor:
    def __init__(
        self, data_dir: Path, plugins: Mapping[str, Any] | PluginRegistry
    ) -> None:
        self.data_dir = data_dir
        self.registry = (
            plugins
            if isinstance(plugins, PluginRegistry)
            else PluginRegistry.from_mapping(plugins, known_harnesses=KNOWN_HARNESSES)
        )
        self.store = SessionStore(data_dir)
        self.watch_hub = WatchHub()
        self.clients = ClientRegistry()
        self.writer_leases = WriterLeases()
        self.store.on_commit = self.watch_hub.wake
        self._refs: dict[str, SessionRef] = {}
        # Called with (session_id, decision, tool) for every bot permission decision;
        # the gateway task wires it to the audit log.
        self.bot_permission_sink: Callable[[str, Decision, str], None] | None = None
        # Returns the env overlay (the bot token) for a restricted session; called at
        # every start and resume, so tokens are never persisted.
        self.bot_token_issuer: Callable[[str], Mapping[str, str]] | None = None
        # Same for agents launched by the bot or its descendants (taint token).
        self.bot_descendant_issuer: Callable[[str], Mapping[str, str]] | None = None
        self.bot_token_revoker: Callable[[str], None] | None = None
        self._address_bindings: dict[str, tuple[Path, str]] = {}
        self._ipc_server: Any = None
        self._socket_path: Path | None = None
        self._event_tasks: set[asyncio.Task[None]] = set()
        self._session_event_tasks: dict[str, asyncio.Task[None]] = {}
        self._idle_reap_tasks: dict[str, asyncio.Task[None]] = {}
        self._idle_reap_clock: Callable[[], float] = time.monotonic
        self._idle_reap_sleep: Callable[[float], Any] = asyncio.sleep
        self._expiry_task: asyncio.Task[None] | None = None
        self._send_locks: dict[object, asyncio.Lock] = {}
        self.interrupt_timeout = 5.0
        self.stop_lock_timeout_s = 5.0
        self._guard_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._guard_approval_responses: set[tuple[str, str]] = set()
        self._startup_tasks: dict[str, asyncio.Task[None]] = {}
        self._startup_specs: dict[str, SessionSpec] = {}
        self._startup_send_pending: set[str] = set()
        self._startup_warned: set[str] = set()
        (
            self._startup_timeout_seconds,
            self._startup_kill_timeout_seconds,
            self._stall_after_seconds,
            self._idle_reap_timeout_s,
        ) = self._timeout_settings()
        self._instance_start_lock = asyncio.Lock()
        self._reserved_instance_starts = 0
        self.takeover: Any | None = None

    def _timeout_settings(self) -> tuple[float, float, float, int]:
        try:
            config = load_config(config_path(), self.registry.known_harnesses())
            return (
                float(getattr(config, "startup_timeout_s", 30)),
                float(getattr(config, "startup_kill_timeout_s", 300)),
                float(getattr(config, "stall_after_s", 600)),
                int(getattr(config, "idle_process_timeout_s", 600)),
            )
        except OSError, ValueError:
            return 30.0, 300.0, 600.0, 600

    def _schedule_idle_reap(self, session_id: str) -> None:
        current = self._idle_reap_tasks.pop(session_id, None)
        if current is not None:
            current.cancel()
        if self._idle_reap_timeout_s == 0:
            return
        row = self.store.get_session(session_id)
        if (
            row is None
            or row["status"] != "idle"
            or row["lifecycle"]
            in {
                "completed",
                "archived",
            }
        ):
            return
        if row["role"] in {"manager-bot", "orchestrator"} and self.clients.has_clients(
            session_id
        ):
            return
        if any(wait["session_id"] == session_id for wait in self.store.pending_waits()):
            return
        self._idle_reap_tasks[session_id] = asyncio.create_task(
            self._reap_idle_session(session_id, self._idle_reap_clock())
        )

    async def _reap_idle_session(self, session_id: str, idle_since: float) -> None:
        try:
            await self._idle_reap_sleep(
                max(
                    0.0,
                    idle_since + self._idle_reap_timeout_s - self._idle_reap_clock(),
                )
            )
            row = self.store.get_session(session_id)
            if (
                row is None
                or row["status"] != "idle"
                or row["lifecycle"]
                in {
                    "completed",
                    "archived",
                }
            ):
                return
            watched_slot = row["role"] in {"manager-bot", "orchestrator"}
            if watched_slot and self.clients.has_clients(session_id):
                return
            pending_wait = any(
                wait["session_id"] == session_id for wait in self.store.pending_waits()
            )
            if pending_wait:
                return
            lock = self._send_locks.setdefault(
                self._session_lock_key(row), asyncio.Lock()
            )
            if lock.locked():
                return
            await lock.acquire()
            try:
                row = self.store.get_session(session_id)
                if row is None or row["status"] != "idle":
                    return
                plugin = self.registry.plugin_for_key(row["backend"])
                ref = self._refs.get(session_id)
                if plugin is None or ref is None:
                    return
                await self._cancel_session_event_task(session_id)
                await plugin.stop(ref)
                await self._update_session_slot(slot_park.park_session, session_id)
                self._refs.pop(session_id, None)
            finally:
                lock.release()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("could not reap idle session %s", session_id)
        finally:
            if self._idle_reap_tasks.get(session_id) is asyncio.current_task():
                self._idle_reap_tasks.pop(session_id, None)

    def _arm_startup_diagnostic(
        self, session_id: str, spec: SessionSpec, started_at: float | None = None
    ) -> None:
        if (
            not spec.prompt
            or session_id in self._startup_tasks
            or session_id in self._startup_warned
        ):
            return
        started_at = time.monotonic() if started_at is None else started_at
        self._startup_specs[session_id] = spec
        self._startup_tasks[session_id] = asyncio.create_task(
            self._startup_timeout(session_id, spec, started_at)
        )

    async def _startup_timeout(
        self, session_id: str, spec: SessionSpec, started_at: float
    ) -> None:
        timeout = self._startup_timeout_seconds
        await asyncio.sleep(max(0.0, timeout - (time.monotonic() - started_at)))
        if session_id not in self._startup_tasks:
            return
        self._startup_warned.add(session_id)
        self.store.append_event(
            session_id,
            "warning",
            {
                "message": startup_diagnostic(
                    spec,
                    sys.platform,
                    time.monotonic() - started_at,
                    str(Path(sys.argv[0]).resolve()),
                    sys.executable,
                )
            },
        )
        kill_s = self._startup_kill_timeout_seconds
        if kill_s <= 0:
            return
        await asyncio.sleep(max(0.0, kill_s - (time.monotonic() - started_at)))
        if self._startup_tasks.get(session_id) is not asyncio.current_task():
            return
        self._startup_tasks.pop(session_id, None)
        self._startup_warned.discard(session_id)
        self._startup_specs.pop(session_id, None)
        await self._kill_silent_start(session_id, spec, started_at)

    async def _kill_silent_start(
        self, session_id: str, spec: SessionSpec, started_at: float
    ) -> None:
        """Stop an open session whose first turn produced no agent output."""
        current = self.store.get_session(session_id)
        if current is None or current["lifecycle"] in {"completed", "archived"}:
            return
        elapsed = int(time.monotonic() - started_at)
        self.store.append_event(
            session_id,
            "error",
            {"message": f"startup silent for {elapsed}s; process stopped"},
        )
        await self._cancel_session_event_task(session_id)
        await self._stop_silent_process(current, spec)
        self.store.update_session(session_id, status="error", idle_status="unknown")
        self._unbind_address_binding(session_id)
        self._refs.pop(session_id, None)

    async def _stop_silent_process(
        self, row: dict[str, Any], spec: SessionSpec
    ) -> None:
        session_id = row["id"]
        ref = self._refs.get(session_id)
        plugin = self.registry.plugin_for_key(spec.provider)
        if ref is None or plugin is None:
            logger.warning(
                "startup watchdog found no live ref/plugin for session %s",
                session_id,
            )
            return
        lock = self._send_locks.get(self._session_lock_key(row))
        if lock is not None and lock.locked():
            logger.warning(
                "startup watchdog stopping session %s while send lock is held",
                session_id,
            )
        try:
            await plugin.stop(ref)
        except Exception:
            logger.exception("failed to stop startup-silent session %s", session_id)

    def _finish_startup_diagnostic(self, session_id: str) -> None:
        if (
            session_id not in self._startup_tasks
            and session_id not in self._startup_warned
            and session_id in self._startup_send_pending
        ):
            return
        task = self._startup_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
        if session_id in self._startup_warned:
            self._startup_warned.remove(session_id)
            self.store.append_event(
                session_id, "activity", {"message": "startup recovered"}
            )
        self._startup_specs.pop(session_id, None)
        self._startup_send_pending.discard(session_id)

    def _cancel_startup_diagnostic(self, session_id: str) -> None:
        task = self._startup_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
        self._startup_specs.pop(session_id, None)
        self._startup_send_pending.discard(session_id)
        self._startup_warned.discard(session_id)

    async def _recover_plugin_orphans(self) -> set[str]:
        unavailable_sessions: set[str] = set()
        for plugin in self.registry.plugins():
            recover_orphans = getattr(plugin, "recover_orphans", None)
            if callable(recover_orphans):
                recover = cast("Callable[[], Awaitable[set[str]]]", recover_orphans)
                unavailable_sessions.update(await recover())
        return unavailable_sessions

    def _mark_recovered_session_unavailable(
        self, row: Mapping[str, Any], unavailable_sessions: set[str]
    ) -> bool:
        try:
            remote_session_id = json.loads(row["ref"]).get("session_id")
        except TypeError, ValueError:
            remote_session_id = None
        if remote_session_id not in unavailable_sessions:
            return False
        self.store.append_event(
            row["id"],
            "error",
            {"message": "Plugin process recovery marked session unavailable"},
        )
        self.store.update_session(row["id"], status="error", idle_status="unknown")
        self._unbind_address_binding(row["id"])
        self._refs.pop(row["id"], None)
        return True

    @staticmethod
    def _max_restart_count() -> int:
        path = config_path()
        return (
            load_config(path).max_no_progress_restarts
            if path.exists()
            else default_config().max_no_progress_restarts
        )

    async def _startup_session_rows(self) -> list[dict[str, Any]]:
        self._backfill_approval_waits()
        unavailable_sessions = await self._recover_plugin_orphans()
        rows = self.store.sessions()
        return [
            row
            for row in rows
            if not self._mark_recovered_session_unavailable(row, unavailable_sessions)
        ]

    async def start(self) -> None:  # noqa: PLR0915 - ordered recovery lifecycle
        max_restarts = self._max_restart_count()
        rows = await self._startup_session_rows()
        for row in rows:
            plugin = self.registry.plugin_for_key(row["backend"])
            if plugin is None or not plugin.capabilities.resume:
                self.store.update_session(
                    row["id"], status="error", idle_status="unknown"
                )
                self._unbind_address_binding(row["id"])
                continue
            status_event = self.store.last_status_event(row["id"])
            quiet_idle = _is_quiet_idle(
                row["status"], status_event, self.store.open_intents(row["id"])
            )
            if row["no_progress_restarts"] >= max_restarts and not quiet_idle:
                self._refs.pop(row["id"], None)
                continue
            progress_seq = self.store.latest_progress_sequence(row["id"])
            prior_progress_seq = self.store.latest_progress_sequence(
                row["id"], through=int(row["seq_at_last_start"])
            )
            if quiet_idle:
                restarts = int(row["no_progress_restarts"])
            elif progress_seq == prior_progress_seq:
                restarts = int(row["no_progress_restarts"]) + 1
            else:
                restarts = 0
            self.store.update_session(
                row["id"],
                no_progress_restarts=restarts,
                seq_at_last_start=progress_seq,
            )
            if restarts >= max_restarts and not quiet_idle:
                parked_seq = self.store.append_event(
                    row["id"],
                    "parked",
                    {
                        "reason": "session made no event progress across restarts",
                        "no_progress_restarts": restarts,
                    },
                )
                self.store.update_session(
                    row["id"], status="error", seq_at_last_start=parked_seq
                )
                self._unbind_address_binding(row["id"])
                self._refs.pop(row["id"], None)
                continue
            resume_started_at = time.monotonic()
            resume_spec: SessionSpec | None = None
            try:
                ref = SessionRef(**json.loads(row["ref"]))
                spec_loader = getattr(plugin, "_load_spec", None)
                resume_spec = (
                    cast("SessionSpec | None", spec_loader(ref))
                    if callable(spec_loader)
                    else None
                )
                self._refs[row["id"]] = await plugin.resume(ref)
                await self._update_session_slot(slot_park.unpark_session, row["id"])
                closed = row["lifecycle"] in {"completed", "archived"}
                persistent = plugin.capabilities.persistent_process
                if resume_spec is not None and persistent and not closed:
                    await self._prepare_resumed_startup(row, resume_spec)
                try:
                    await self._reconcile_approval_waits(row["id"], plugin, ref)
                except Exception:
                    logger.exception(
                        "could not reconcile pending approvals for session %s",
                        row["id"],
                    )
                resumed_seq = self._record_resume(row["id"])
                self.store.update_session(
                    row["id"],
                    status="running",
                    idle_status="unknown",
                    seq_at_last_start=resumed_seq,
                )
                self._watch_events(row["id"], plugin, ref, row["last_event_seq"])
            except (RuntimeError, ValueError, TimeoutError) as exc:
                if (
                    resume_spec is not None
                    and plugin.capabilities.persistent_process
                    and startup_timeout_error(exc)
                ):
                    append_startup_diagnostic(
                        exc,
                        resume_spec,
                        time.monotonic() - resume_started_at,
                        str(Path(sys.argv[0]).resolve()),
                        sys.executable,
                    )
                    self.store.append_event(
                        row["id"],
                        "error",
                        {"message": str(exc.args[0]) if exc.args else str(exc)},
                    )
                failed_restarts = int(row["no_progress_restarts"]) + 1
                if failed_restarts >= max_restarts:
                    parked_seq = self.store.append_event(
                        row["id"],
                        "parked",
                        {
                            "reason": "session made no event progress across restarts",
                            "no_progress_restarts": failed_restarts,
                        },
                    )
                    self.store.update_session(
                        row["id"],
                        status="error",
                        idle_status="unknown",
                        no_progress_restarts=failed_restarts,
                        seq_at_last_start=parked_seq,
                    )
                    self._unbind_address_binding(row["id"])
                else:
                    self.store.update_session(
                        row["id"],
                        status="error",
                        idle_status="unknown",
                        no_progress_restarts=failed_restarts,
                    )
                    self._unbind_address_binding(row["id"])
        if self.guard_enabled():
            for wait in self.store.waits_by_kind("approval", "pending"):
                request_id = wait["payload"].get("request_id")
                if (
                    isinstance(request_id, str)
                    and self.store.guard_verdict_for(wait["session_id"], request_id)
                    is None
                ):
                    self._schedule_guard(
                        wait["session_id"], request_id, wait["payload"]
                    )
        self._expire_unavailable_approvals()
        if self._expiry_task is None or self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expire_due_waits_loop())
            self._event_tasks.add(self._expiry_task)
        await self._recover_planner_start_intents()
        await self._restart_unresumable_planners()

    async def _recover_planner_start_intents(self) -> None:
        work_items = WorkItemStore(self.data_dir)
        registry = SessionRegistry(self.data_dir / "registry.json")
        try:
            rows = self.store.sessions()
            for item in work_items.list():
                if item.state != "planning" or item.planner_session is not None:
                    continue
                binding = registry.resolve(f"workitem-{item.id[:40]}")
                match = next(
                    (
                        row
                        for row in rows
                        if binding is not None
                        and json.loads(row["ref"]).get("session_id")
                        == binding.session_id
                        and row["role"] == "planner"
                    ),
                    None,
                )
                if match is not None:
                    work_items.attach_planner(item.id, match["id"])
                else:
                    work_items.reset_planner_start(item.id)
        finally:
            work_items.close()

    async def _restart_unresumable_planners(self) -> None:
        work_items = WorkItemStore(self.data_dir)
        try:
            for row in self.store.sessions():
                plugin = self.registry.plugin_for_key(row["backend"])
                if (
                    row["role"] != "planner"
                    or plugin is None
                    or plugin.capabilities.resume
                ):
                    continue
                item = work_items.for_planner_session(row["id"])
                if item is None or item.state not in {"planning", "asking"}:
                    continue
                try:
                    replacement = await self.start_planner_session(
                        item.id,
                        Path(item.notes_path),
                        item.project,
                        prior_context=work_items.recovery_context(item.id),
                        replacing_session_id=row["id"],
                    )
                    work_items.attach_planner(item.id, replacement.session_id)
                    self.store.update_session(
                        row["id"], status="completed", idle_status="closed"
                    )
                except InstanceCapError as exc:
                    logger.warning(
                        "cap reached, planner not restarted for work item %s (%s/%s)",
                        item.id,
                        exc.live,
                        exc.max_live,
                    )
                except KeyError, RuntimeError, ValueError, OSError:
                    logger.exception(
                        "could not restart planner for work item %s", item.id
                    )
        finally:
            work_items.close()

    async def start_session(self, spec: SessionSpec, role: str) -> SessionRef:
        plugin = self.registry.plugin_for_key(spec.provider)
        if plugin is None:
            raise KeyError(spec.provider)
        return await self._start_session(spec, role, plugin)

    async def _start_session(
        self,
        spec: SessionSpec,
        role: str,
        plugin: RunnerPlugin,
        excluded_live_session_id: str | None = None,
    ) -> SessionRef:
        if is_restricted(spec.profile) and not plugin.capabilities.restricted_profile:
            raise ProfileUnsupported(
                "this harness cannot enforce the restricted profile"
            )
        max_live = self.max_live_instances()
        async with self._instance_start_lock:
            rows = [
                row
                for row in self.store.sessions()
                if row["id"] != excluded_live_session_id
            ]
            live = live_count(rows) + self._reserved_instance_starts
            if over_cap(live, max_live):
                raise InstanceCapError(live, max_live)
            self._reserved_instance_starts += 1

        try:
            return await self._start_reserved_session(spec, role, plugin)
        finally:
            async with self._instance_start_lock:
                self._reserved_instance_starts -= 1

    def max_live_instances(self) -> int:
        path = config_path()
        if not path.exists():
            return default_config().max_live_instances
        return load_config(path, self.registry.known_harnesses()).max_live_instances

    async def _start_reserved_session(
        self, spec: SessionSpec, role: str, plugin: RunnerPlugin
    ) -> SessionRef:
        session_id = uuid.uuid4().hex
        spec = replace(spec, agent_id=session_id, role=role)
        if is_restricted(spec.profile) and self.bot_token_issuer is not None:
            spec = replace(spec, env={**spec.env, **self.bot_token_issuer(session_id)})
        elif is_bot_rooted(spec.launched_by) and self.bot_descendant_issuer is not None:
            overlay = self.bot_descendant_issuer(session_id)
            spec = replace(spec, env={**spec.env, **overlay})
        started_at = time.monotonic()
        try:
            ref = await plugin.start(spec)
        except Exception as exc:
            if plugin.capabilities.persistent_process and startup_timeout_error(exc):
                append_startup_diagnostic(
                    exc,
                    spec,
                    time.monotonic() - started_at,
                    str(Path(sys.argv[0]).resolve()),
                    sys.executable,
                )
            raise
        self._refs[session_id] = ref
        self.store.create_session(
            session_id,
            spec.provider,
            {"provider": ref.provider, "session_id": ref.session_id},
            role,
            harness=spec.runner_harness,
            agent_id=session_id,
        )
        self.store.update_session(session_id, status="running", idle_status="unknown")
        self._watch_events(session_id, plugin, ref, 0)
        if plugin.capabilities.persistent_process:
            self._startup_specs[session_id] = spec
            if not spec.prompt:
                self._startup_send_pending.add(session_id)
            if spec.prompt:
                self._arm_startup_diagnostic(session_id, spec, started_at)
        return SessionRef(ref.provider, session_id)

    async def start_planner_session(
        self,
        item_id: str,
        notes_path: Path,
        project: str,
        role_config_path: Path | None = None,
        prior_context: str = "",
        replacing_session_id: str | None = None,
    ) -> SessionRef:
        """Resolve planner role, start it through the configured adapter,
        and bind it."""
        config = load_config(
            role_config_path or config_path(), self.registry.known_harnesses()
        )
        role = config.resolve("planner")
        address = f"workitem-{item_id[:40]}"
        token = base64.b32encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
        marker = f"[varde-address: {address} vt1.{token}]"
        prompt = (
            f"{marker}\nPlan the user's request. Read the complete request from "
            f"this notes file without altering it: {notes_path.resolve()}\n"
            f"Your sender address is {address}. Send every message with "
            f"`varde msg send --from {address} --to main --kind needs-user "
            "[--notes <absolute-notes-path>] <one-line-text>`; do not rely on "
            "implicit sender resolution. For unresolved questions, attach JSON "
            "notes with asked, why, options (each with label and consequence), "
            "recommendation, and sources. When complete, save the plan to a file, "
            "then send exactly one plan-ready message using the same command with "
            "--kind needs-user and JSON notes with those context fields plus "
            "work_item_event=plan_ready, "
            "kind=plan_ready, and plan_path set to its absolute path. Keep the notes "
            "file in this work item's notes directory. Do not send duplicate "
            "questions or another plan-ready message. "
            f"{prior_context}"
        )
        workspace = Path(project).expanduser()
        cwd = workspace.resolve() if workspace.is_dir() else Path.cwd()
        candidates = (
            Model(role.harness, role.model, role.reasoning_effort, role.mode),
            *role.fallback,
        )
        if not workspace.is_dir():
            try:
                workspaces = await self.registry.list_workspaces(candidates[0].harness)
            except RuntimeError, OSError:
                workspaces = []
            listed = next(
                (entry for entry in workspaces if entry.get("id") == project), None
            )
            if listed is not None and isinstance(listed.get("cwd"), str):
                cwd = Path(listed["cwd"]).expanduser().resolve()
        registry = SessionRegistry(self.data_dir / "registry.json")
        registry.expect_marker(marker)
        session: SessionRef | None = None
        started_model: Model | None = None
        for index, model in enumerate(candidates):
            plugin = self.registry.plugin_for(model.harness)
            settings = plugin.session_settings(model)
            spec = SessionSpec(
                provider=self.registry.provider_key(model.harness),
                model=settings.model,
                workspace_id=project,
                cwd=str(cwd),
                prompt=prompt,
                reasoning_effort=settings.reasoning_effort,
                mode_id=settings.mode_id,
                runner_harness=model.harness,
            )
            try:
                session = await self._start_session(
                    spec,
                    "planner",
                    plugin,
                    excluded_live_session_id=replacing_session_id,
                )
                started_model = model
                break
            except InstanceCapError:
                raise
            except Exception as exc:
                await self._stop_partial_start(spec.provider, exc)
                if (
                    index == len(candidates) - 1
                    or "provider_limit" not in config.allow_fallback_only_on
                    or not plugin_is_provider_limit_error(plugin, exc)
                ):
                    raise
        if session is None or started_model is None:
            raise RuntimeError("planner fallback chain did not start")
        stored = self.store.get_session(session.session_id)
        if stored is None:
            raise RuntimeError("planner session was not persisted")
        remote_id = json.loads(stored["ref"])["session_id"]
        binding = SessionBinding(
            address=address,
            harness=started_model.harness,
            adapter=session.provider,
            session_id=remote_id,
            role="planner",
            plan_id=item_id,
        )
        if not registry.bind_first_prompt(prompt, binding):
            raise RuntimeError("planner session address binding failed")
        return session

    async def _stop_partial_start(self, provider: str, error: Exception) -> None:
        remote_id = getattr(error, "session_id", None)
        if not isinstance(remote_id, str) or not remote_id:
            return
        plugin = self.registry.plugin_for_key(provider)
        if plugin is None:
            return
        try:
            await plugin.stop(SessionRef(provider, remote_id))
        except Exception:
            logger.exception(
                "could not stop partially started planner session %s", remote_id
            )

    def _watch_events(
        self,
        session_id: str,
        plugin: RunnerPlugin,
        ref: SessionRef,
        after_sequence: int,
    ) -> None:
        task = asyncio.create_task(
            self._consume_events(session_id, plugin, ref, after_sequence)
        )
        self._session_event_tasks[session_id] = task
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)
        task.add_done_callback(
            lambda done: (
                self._session_event_tasks.pop(session_id, None)
                if self._session_event_tasks.get(session_id) is done
                else None
            )
        )

    async def _consume_events(
        self,
        session_id: str,
        plugin: RunnerPlugin,
        ref: SessionRef,
        after_sequence: int,
    ) -> None:
        try:
            events_after = getattr(plugin, "events_after", None)
            events = (
                events_after(ref, after_sequence)
                if events_after is not None
                else plugin.events(ref)
            )
            async for event in events:
                await self.record_event(session_id, event.kind, event.payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("event watcher failed for session %s", session_id)
            row = self.store.get_session(session_id)
            if row is not None and row["lifecycle"] not in {"completed", "archived"}:
                self.store.update_session(
                    session_id, status="error", idle_status="unknown"
                )
                self._unbind_address_binding(session_id)
        finally:
            self._cancel_startup_diagnostic(session_id)

    def idle_status(self, session_id: str) -> str:
        row = self.store.get_session(session_id)
        if row is None:
            raise KeyError(session_id)
        plugin = self.registry.plugin_for_key(row["backend"])
        if plugin is None:
            raise RuntimeError("session plugin is unavailable")
        if not plugin.capabilities.idle_status:
            return "unknown"
        return row["idle_status"]

    async def watch(
        self,
        session_id: str,
        after_seq: int | None = None,
        *,
        client_id: str,
        role: ClientRole | str,
    ) -> AsyncGenerator[dict[str, Any]]:
        row = self._session_row(session_id)
        resolved_id = row["id"] if row is not None else session_id
        self.clients.attach(resolved_id, client_id, role)
        try:
            async for message in self.watch_hub.watch(
                self.store, resolved_id, after_seq
            ):
                yield message
        finally:
            last_attachment = self.clients.detach(resolved_id, client_id)
            if last_attachment:
                self.writer_leases.release(resolved_id, client_id)
                self._schedule_idle_reap(resolved_id)

    async def send(
        self,
        session_id: str,
        prompt: str,
        harness: str | None = None,
        *,
        client_id: str | None = None,
        request_id: str | None = None,
        takeover_holder: bool = False,
    ) -> SendOutcome:
        return await self._send(
            session_id,
            prompt,
            harness,
            client_id=client_id,
            request_id=request_id,
            takeover_holder=takeover_holder,
        )

    async def send_with_interrupt(
        self,
        session_id: str,
        prompt: str,
        harness: str | None = None,
        *,
        client_id: str | None = None,
        request_id: str | None = None,
    ) -> SendOutcome:
        return await self._send_interrupt(
            session_id,
            prompt,
            harness,
            client_id=client_id,
            request_id=request_id,
        )

    async def _send(
        self,
        session_id: str,
        prompt: str,
        harness: str | None = None,
        *,
        client_id: str | None = None,
        request_id: str | None = None,
        takeover_holder: bool = False,
    ) -> SendOutcome:
        initial_row = self._session_row(session_id, harness)
        system = self._authorize_write(session_id, initial_row, client_id)
        sender_class = (
            "holder" if takeover_holder else "other" if system else "user_control"
        )
        if (
            initial_row is not None
            and self.takeover is not None
            and self.takeover.should_queue(
                str(initial_row.get("agent_id") or initial_row["id"]),
                sender_class,
                prompt,
                request_id=request_id,
                supervisor=self,
            )
        ):
            return SendOutcome.QUEUED
        if not system:
            self._acquire_interactive_lease(initial_row, client_id)
        retain_lease = False
        try:
            target = await self._target_for_send(session_id, harness)
            if target is None:
                return (
                    SendOutcome.FAILED
                    if initial_row is not None
                    else SendOutcome.NOT_FOUND
                )
            row, plugin, ref, lock_key = target

            async def submit() -> SendOutcome:
                if row is not None:
                    self.store.update_session(
                        row["id"], status="running", idle_status="running"
                    )
                    self._arm_pending_startup(row, plugin, prompt)
                try:
                    await _send_plugin_prompt(plugin, ref, prompt, request_id)
                except Exception:  # noqa: BLE001 - expose plugin failures as outcomes
                    if row is not None:
                        self._cancel_startup_diagnostic(row["id"])
                        if self._session_open(row["id"]):
                            self.store.update_session(
                                row["id"], status="running", idle_status="unknown"
                            )
                    outcome = SendOutcome.FAILED
                else:
                    if row is not None and self._session_open(row["id"]):
                        self.store.update_session(row["id"], no_progress_restarts=0)
                    outcome = SendOutcome.SENT
                if (
                    request_id is not None
                    and row is not None
                    and outcome == SendOutcome.SENT
                ):
                    self.store.record_send_admission(row["id"], request_id, outcome)
                return outcome

            def admission() -> SendOutcome | None:
                if request_id is None or row is None:
                    return None
                recorded = self.store.get_send_admission(row["id"], request_id)
                return SendOutcome(recorded) if recorded is not None else None

            outcome = await self._send_under_lock(
                lock_key, plugin, ref, row, submit, admission
            )
            retain_lease = not system and outcome == SendOutcome.SENT
            return outcome
        finally:
            if not system and not retain_lease:
                self._release_interactive_lease(initial_row, client_id)

    async def _send_under_lock(
        self,
        lock_key: object,
        plugin: RunnerPlugin,
        ref: SessionRef,
        row: dict[str, Any] | None,
        submit: Callable[[], Awaitable[SendOutcome]],
        admission: Callable[[], SendOutcome | None] | None = None,
    ) -> SendOutcome:
        lock = self._send_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            admitted = admission() if admission is not None else None
            if admitted is not None:
                return admitted
            if await self._live_idle(plugin, ref, row) != "idle":
                return SendOutcome.SKIPPED_BUSY
            return await submit()

    def _arm_pending_startup(
        self, row: dict[str, Any], plugin: RunnerPlugin, prompt: str
    ) -> None:
        """Arm the startup watchdog for the first prompt of a resumed session."""
        if not plugin.capabilities.persistent_process:
            return
        startup_spec = self._startup_specs.get(row["id"])
        if startup_spec is None or row["id"] not in self._startup_send_pending:
            return
        self._startup_send_pending.discard(row["id"])
        self._arm_startup_diagnostic(row["id"], replace(startup_spec, prompt=prompt))

    async def _send_launch_prompt(self, row: dict[str, Any], prompt: str) -> bool:
        plugin = self.registry.plugin_for_key(row["backend"])
        ref = self._refs.get(row["id"])
        if plugin is None or ref is None:
            return False

        async def submit() -> SendOutcome:
            try:
                await _send_plugin_prompt(plugin, ref, prompt, f"launch:{row['id']}")
            except Exception:
                logger.exception("could not resend launch prompt for %s", row["id"])
                return SendOutcome.FAILED
            return SendOutcome.SENT

        return (
            await self._send_under_lock(
                self._session_lock_key(row), plugin, ref, row, submit
            )
        ) == SendOutcome.SENT

    async def _prepare_resumed_startup(
        self,
        row: dict[str, Any],
        spec: SessionSpec,
    ) -> None:
        session_id = row["id"]
        self._startup_specs[session_id] = spec
        self._startup_send_pending.add(session_id)
        had_running_status = self.store.has_status_event(session_id, "running")
        if (
            not spec.prompt
            or self.store.has_agent_output(session_id)
            or had_running_status
        ):
            return
        self._startup_send_pending.discard(session_id)
        self._arm_startup_diagnostic(session_id, spec)
        if await self._send_launch_prompt(row, spec.prompt):
            self.store.append_event(
                session_id, "activity", {"message": "launch prompt resent"}
            )

    async def _send_interrupt(
        self,
        session_id: str,
        prompt: str,
        harness: str | None = None,
        *,
        client_id: str | None = None,
        request_id: str | None = None,
    ) -> SendOutcome:
        initial_row = self._session_row(session_id, harness)
        system = self._authorize_write(session_id, initial_row, client_id)
        if request_id is not None and initial_row is not None:
            recorded = self.store.get_send_admission(initial_row["id"], request_id)
            if recorded is not None:
                return SendOutcome(recorded)
        if initial_row is not None and self.takeover is not None:
            queued = self.takeover.should_queue(
                str(initial_row.get("agent_id") or initial_row["id"]),
                "user_control",
                prompt,
                request_id=request_id,
                supervisor=self,
            )
            if queued:
                return SendOutcome.QUEUED
        if not system:
            self._acquire_interactive_lease(initial_row, client_id)
        retain_lease = False
        try:
            target = await self._target_for_send(session_id, harness)
            if target is None:
                return (
                    SendOutcome.FAILED
                    if initial_row is not None
                    else SendOutcome.NOT_FOUND
                )
            row, plugin, ref, lock_key = target
            if not plugin.capabilities.interrupt:
                return SendOutcome.FAILED_INTERRUPT
            interruptible_plugin = cast("InterruptiblePlugin", plugin)

            async def interrupt_and_submit() -> SendOutcome:
                lock = self._send_locks.setdefault(lock_key, asyncio.Lock())
                async with lock:
                    try:
                        await interruptible_plugin.interrupt(ref)
                        await asyncio.wait_for(
                            self._wait_until_idle(row, plugin, ref),
                            timeout=self.interrupt_timeout,
                        )
                    except Exception:  # noqa: BLE001 - failed interruption forbids submission
                        return SendOutcome.FAILED_INTERRUPT
                    if row is not None and self._session_open(row["id"]):
                        self.store.update_session(
                            row["id"], status="running", idle_status="running"
                        )
                        self._arm_pending_startup(row, plugin, prompt)
                    try:
                        await _send_plugin_prompt(plugin, ref, prompt, request_id)
                    except Exception:  # noqa: BLE001 - expose plugin failure as an outcome
                        if row is not None and self._session_open(row["id"]):
                            self.store.update_session(
                                row["id"], status="running", idle_status="unknown"
                            )
                        return SendOutcome.FAILED
                    if row is not None and self._session_open(row["id"]):
                        self.store.update_session(row["id"], no_progress_restarts=0)
                    if request_id is not None and row is not None:
                        self.store.record_send_admission(
                            row["id"], request_id, SendOutcome.SENT
                        )
                    return SendOutcome.SENT

            outcome = await interrupt_and_submit()
            retain_lease = not system and outcome == SendOutcome.SENT
            return outcome
        finally:
            if not system and not retain_lease:
                self._release_interactive_lease(initial_row, client_id)

    def _session_open(self, session_id: str) -> bool:
        """Re-read the row; closed sessions must not be marked running again."""
        current = self.store.get_session(session_id)
        return current is not None and current["lifecycle"] not in {
            "completed",
            "archived",
        }

    def _authorize_write(
        self,
        session_id: str,
        row: dict[str, Any] | None,
        client_id: str | None,
    ) -> bool:
        if client_id is None or client_id in SYSTEM_CLIENT_IDS:
            return True
        resolved_id = row["id"] if row is not None else session_id
        role = self.clients.role(resolved_id, client_id)
        if role is None:
            raise UnknownClient(client_id)
        if role == ClientRole.OBSERVER:
            raise ObserverReadOnly(client_id)
        return False

    def _acquire_interactive_lease(
        self, row: dict[str, Any] | None, client_id: str | None
    ) -> None:
        if row is None:
            raise UnknownClient(client_id or "")
        session_id = row["id"]
        if (
            client_id is None
            or self.clients.role(session_id, client_id) != ClientRole.WRITER
        ):
            raise UnknownClient(client_id or "")
        self.writer_leases.acquire(session_id, client_id)

    def _release_interactive_lease(
        self, row: dict[str, Any] | None, client_id: str | None
    ) -> None:
        if row is not None and client_id is not None:
            self.writer_leases.release(row["id"], client_id)

    async def _update_session_slot(
        self, action: Callable[[str], bool], session_id: str
    ) -> None:
        """Park or unpark a session's slot off the event loop; never raises."""
        await asyncio.to_thread(action, session_id)

    async def _target(
        self, session_id: str, harness: str | None
    ) -> tuple[dict[str, Any] | None, RunnerPlugin, SessionRef, object] | None:
        row = self._session_row(session_id, harness)
        if row is not None and row["id"] in self._refs:
            plugin = self.registry.plugin_for_key(row["backend"])
            if plugin is not None:
                ref = self._refs[row["id"]]
                return row, plugin, ref, (id(plugin), ref.session_id)
        if row is not None:
            return None
        candidates = (
            [harness] if harness is not None else sorted(self.registry.harnesses())
        )
        for candidate in candidates:
            try:
                plugin = self.registry.plugin_for(candidate)
                provider = self.registry.provider_key(candidate)
            except KeyError:
                if harness is None:
                    continue
                plugin = self.registry.plugin_for_key(candidate)
                if plugin is None:
                    continue
                provider = candidate
            ref = SessionRef(provider, session_id)
            inspect = getattr(plugin, "inspect", None)
            if (
                harness is None
                and callable(inspect)
                and not await self._matches_unmanaged(plugin, ref, inspect)
            ):
                continue
            return None, plugin, ref, (id(plugin), session_id)
        return None

    async def _target_for_send(
        self,
        session_id: str,
        harness: str | None,
        settings: ResumeSettings | None = None,
    ) -> tuple[dict[str, Any] | None, RunnerPlugin, SessionRef, object] | None:
        target = await self._target(session_id, harness)
        if target is not None:
            return target
        row = self._session_row(session_id, harness)
        if row is None:
            return None
        plugin = self.registry.plugin_for_key(row["backend"])
        if plugin is None or not plugin.capabilities.resume:
            return None
        ref = SessionRef(**json.loads(row["ref"]))
        started_at = time.monotonic()
        spec_loader = getattr(plugin, "_load_spec", None)
        spec = (
            cast("SessionSpec | None", spec_loader(ref))
            if callable(spec_loader)
            else None
        )
        self._reissue_bot_token(row, plugin, ref)
        try:
            ref = await resume_plugin(plugin, ref, settings)
        except UnsupportedCapability:
            raise
        except (RuntimeError, ValueError, TimeoutError) as exc:
            if (
                spec is not None
                and plugin.capabilities.persistent_process
                and startup_timeout_error(exc)
            ):
                append_startup_diagnostic(
                    exc,
                    spec,
                    time.monotonic() - started_at,
                    str(Path(sys.argv[0]).resolve()),
                    sys.executable,
                )
                self.store.append_event(
                    row["id"],
                    "error",
                    {"message": str(exc.args[0]) if exc.args else str(exc)},
                )
            return None
        self._refs[row["id"]] = ref
        await self._update_session_slot(slot_park.unpark_session, row["id"])
        if settings is not None and settings.mode_id:
            self.store.update_session(row["id"], mode=settings.mode_id)
            if spec is not None:
                spec = replace(spec, mode_id=settings.mode_id)
        if spec is not None and plugin.capabilities.persistent_process:
            self._startup_specs[row["id"]] = spec
            self._startup_send_pending.add(row["id"])
        self.store.update_session(row["id"], status="running", idle_status="unknown")
        self._record_resume(row["id"])
        row = self.store.get_session(row["id"])
        if row is None:
            return None
        self.store.update_session(row["id"], seq_at_last_start=row["last_event_seq"])
        row = self.store.get_session(row["id"])
        if row is None:
            return None
        self._watch_events(row["id"], plugin, ref, row["last_event_seq"])
        return row, plugin, ref, (id(plugin), ref.session_id)

    def _record_resume(self, session_id: str) -> int:
        intents = self.store.open_intents(session_id)
        return self.store.append_event(
            session_id,
            "resume",
            {
                "open_intents": [
                    {
                        "call_id": item["payload"].get("call_id"),
                        "tool": item["payload"].get("tool"),
                    }
                    for item in intents
                ]
            },
        )

    async def _matches_unmanaged(
        self, plugin: RunnerPlugin, ref: SessionRef, inspect: object
    ) -> bool:
        inspect_method = cast(
            "Callable[[SessionRef], Awaitable[dict[str, Any]]]", inspect
        )
        try:
            snapshot = await inspect_method(ref)
        except Exception:  # noqa: BLE001 - failed lookup means try another harness
            return False
        return isinstance(snapshot, dict) and not snapshot.get("not_found")

    async def _live_idle(
        self, plugin: RunnerPlugin, ref: SessionRef, row: dict[str, Any] | None
    ) -> str:
        status, snapshot = await self._live_status(plugin, ref, row)
        if (
            status != "idle"
            and snapshot is not None
            and snapshot.get("archived")
            and snapshot.get("status") == "closed"
        ):
            return "idle"
        return status

    async def _live_status(
        self, plugin: RunnerPlugin, ref: SessionRef, row: dict[str, Any] | None
    ) -> tuple[str, dict[str, Any] | None]:
        status = row["idle_status"] if row is not None else "unknown"
        if plugin.capabilities.idle_status:
            method = getattr(plugin, "idle_status", None)
            if callable(method):
                idle_status = cast("Callable[[SessionRef], Awaitable[str]]", method)
                status = await idle_status(ref)
        inspect = getattr(plugin, "inspect", None)
        snapshot: dict[str, Any] | None = None
        if status != "idle" and callable(inspect):
            inspect_method = cast(
                "Callable[[SessionRef], Awaitable[dict[str, Any]]]", inspect
            )
            value = await inspect_method(ref)
            snapshot = value if isinstance(value, dict) else None
        return status, snapshot

    async def is_idle(self, session_id: str, harness: str | None = None) -> bool:
        return await self.target_idle_status(session_id, harness) == "idle"

    async def _live_idle_status(
        self, plugin: RunnerPlugin, ref: SessionRef, stored: str
    ) -> str:
        """Return the plugin's live idle status, or `stored` when unavailable."""
        method = getattr(plugin, "idle_status", None)
        if not plugin.capabilities.idle_status or not callable(method):
            return stored
        try:
            return await cast("Callable[[SessionRef], Awaitable[str]]", method)(ref)
        except Exception:  # noqa: BLE001 - stored status remains usable
            return stored

    @staticmethod
    def _process_alive(plugin: RunnerPlugin, ref: SessionRef) -> bool | None:
        """Return whether the child process is alive, or None when unknown."""
        alive = getattr(plugin, "process_alive", None)
        if not callable(alive):
            return None
        try:
            return bool(alive(ref))
        except Exception:  # noqa: BLE001 - unknown is not evidence of death
            return None

    async def liveness(
        self, session_id: str, pending_approvals: int | None = None
    ) -> Liveness:
        row = self.store.get_session(session_id)
        if row is None:
            return Liveness("closed")
        idle_status = str(row.get("idle_status", "unknown"))
        process_alive: bool | None = None
        ref = self._refs.get(session_id)
        plugin = self.registry.plugin_for_key(str(row.get("backend", "")))
        if ref is not None and plugin is not None:
            idle_status = await self._live_idle_status(plugin, ref, idle_status)
            process_alive = self._process_alive(plugin, ref)
        age_s = event_age_s(self.store.last_event_at(session_id), datetime.now(UTC))
        pending = pending_approvals
        if pending is None:
            pending = sum(
                wait["session_id"] == session_id
                for wait in self.store.waits_by_kind("approval", "pending")
            )
        return derive_liveness(
            lifecycle=str(row.get("lifecycle", "idle")),
            idle_status=idle_status,
            last_event_age_s=age_s,
            process_alive=process_alive,
            pending_approvals=pending,
            stall_after_s=self._stall_after_seconds,
        )

    async def target_idle_status(
        self, session_id: str, harness: str | None = None
    ) -> str | dict[str, Any]:
        target = await self._target(session_id, harness)
        if target is None:
            row = self._session_row(session_id, harness)
            if row is not None:
                return "error" if row["status"] == "error" else "unknown"
            return "not-found"
        row, plugin, ref, lock_key = target
        lock = self._send_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            status, snapshot = await self._live_status(plugin, ref, row)
            archived = bool(row and row["lifecycle"] == "archived")
            if snapshot is not None:
                archived = bool(snapshot.get("archived", archived))
                if status == "unknown" and snapshot.get("status") == "closed":
                    status = "closed"
            return {"status": status, "archived": True} if archived else status

    def _session_row(
        self, session_id: str, harness: str | None = None
    ) -> dict[str, Any] | None:
        row = self.store.get_session(session_id)
        if row is not None and (harness is None or row.get("harness") == harness):
            return row
        for candidate in self.store.sessions():
            try:
                ref = json.loads(candidate["ref"])
            except TypeError, ValueError:
                continue
            matches_harness = harness is None or candidate.get("harness") == harness
            if matches_harness and (
                candidate["agent_id"] == session_id
                or ref.get("session_id") == session_id
            ):
                return candidate
        return None

    def resolve_session(self, agent_id: str) -> dict[str, Any] | None:
        """Return the managed session row for an agent id, if one exists."""
        return self._session_row(agent_id)

    async def stop(self, agent_id: str, client_id: str) -> None:
        row = self.resolve_session(agent_id)
        if row is None:
            raise KeyError(agent_id)
        self._authorize_write(agent_id, row, client_id)
        session_id = row["id"]
        lock_key = self._session_lock_key(row)
        lock = self._send_locks.setdefault(lock_key, asyncio.Lock())
        acquired = await self._acquire_stop_lock(lock)
        try:
            row = self.store.get_session(session_id)
            if row is None or row["lifecycle"] in {"completed", "archived"}:
                self.writer_leases.clear(session_id)
                return
            if not acquired:
                await self.record_event(
                    session_id,
                    "activity",
                    {"message": "stop proceeded without send lock"},
                )
            self._cancel_startup_diagnostic(session_id)
            await self._cancel_session_event_task(session_id)
            plugin = self.registry.plugin_for_key(row["backend"])
            ref = self._refs.get(session_id)
            if plugin is not None and ref is not None:
                await plugin.stop(ref)
            self._refs.pop(session_id, None)
            self.store.update_session(
                session_id, status="completed", idle_status="closed"
            )
            if self.takeover is not None:
                self.takeover.release_for_lifecycle(agent_id, self)
            self._unbind_address_binding(session_id)
            self.writer_leases.clear(session_id)
            self._revoke_bot_token(session_id)
        finally:
            if acquired:
                lock.release()

    async def archive(self, agent_id: str, client_id: str) -> None:
        """Close Varde tracking by removing the live ref; leave the process alone."""
        row = self.resolve_session(agent_id)
        if row is None:
            raise KeyError(agent_id)
        self._authorize_write(agent_id, row, client_id)
        session_id = row["id"]
        lock_key = self._session_lock_key(row)
        lock = self._send_locks.setdefault(lock_key, asyncio.Lock())
        acquired = await self._acquire_stop_lock(lock)
        try:
            row = self.store.get_session(session_id)
            if row is None:
                raise KeyError(agent_id)
            if row["lifecycle"] == "running":
                raise RuntimeError("cannot archive a running session")
            if not acquired:
                await self.record_event(
                    session_id,
                    "activity",
                    {"message": "stop proceeded without send lock"},
                )
            self._cancel_startup_diagnostic(session_id)
            self.store.update_session(session_id, lifecycle="archived")
            if self.takeover is not None:
                self.takeover.release_for_lifecycle(agent_id, self)
            ref = self._refs.pop(session_id, None)
            plugin = self.registry.plugin_for_key(row["backend"])
            remove_spec = getattr(plugin, "remove_spec", None)
            if callable(remove_spec):
                if ref is None:
                    ref = SessionRef(**json.loads(row["ref"]))
                remove_spec(ref.session_id)
            self._unbind_address_binding(session_id)
            self.writer_leases.clear(session_id)
            self._revoke_bot_token(session_id)
        finally:
            if acquired:
                lock.release()

    async def _acquire_stop_lock(self, lock: asyncio.Lock) -> bool:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self.stop_lock_timeout_s)
        except TimeoutError:
            return False
        return True

    def register_address_binding(
        self, agent_id: str, working_dir: Path, remote_session_id: str
    ) -> None:
        root = data_root(working_dir)
        self._address_bindings[agent_id] = (root, remote_session_id)
        self.store.set_address_binding(agent_id, str(root), remote_session_id)

    def _unbind_address_binding(self, agent_id: str) -> None:
        try:
            binding = self._address_bindings.pop(agent_id, None)
            persisted = self.store.get_address_binding(agent_id)
            self.store.delete_address_binding(agent_id)
            if binding is None and persisted is not None:
                binding = (
                    Path(persisted["working_dir"]),
                    persisted["remote_session_id"],
                )
            if binding is None:
                return
            from varde_data.config import load_data_config
            from varde_data.open import open_data

            working_dir, remote_session_id = binding
            open_data(data_root(working_dir), load_data_config()).addresses.unbind(
                remote_session_id, datetime.now(UTC)
            )
        except Exception:
            logger.exception("could not unbind address for session %s", agent_id)

    async def interrupt(self, agent_id: str, client_id: str) -> SendOutcome | None:
        row = self.resolve_session(agent_id)
        if row is None:
            raise KeyError(agent_id)
        system = self._authorize_write(agent_id, row, client_id)
        if not system:
            self.writer_leases.preempt_bot(row["id"], client_id or "")
            self._acquire_interactive_lease(row, client_id)
        lease_row = row
        try:
            target = await self._target(agent_id, None)
            if target is None:
                raise RuntimeError("session is not live")
            target_row, plugin, ref, lock_key = target
            if not plugin.capabilities.interrupt:
                raise UnsupportedCapability("interrupt is not supported by this plugin")
            interruptible_plugin = cast("InterruptiblePlugin", plugin)
            lock = self._send_locks.setdefault(lock_key, asyncio.Lock())
            async with lock:
                try:
                    await interruptible_plugin.interrupt(ref)
                    await asyncio.wait_for(
                        self._wait_until_idle(target_row, plugin, ref),
                        timeout=self.interrupt_timeout,
                    )
                except Exception:  # noqa: BLE001 - a failed interrupt cannot be retried here
                    return SendOutcome.FAILED_INTERRUPT
                return None
        finally:
            if not system:
                self._release_interactive_lease(lease_row, client_id)

    async def set_mode(self, agent_id: str, client_id: str, mode: str) -> None:
        """Stop the session, then resume it with a new mode."""
        row = self.resolve_session(agent_id)
        if row is None:
            raise KeyError(agent_id)
        if row["role"] == BOT_ROLE:
            raise UnsupportedCapability("a restricted session cannot change mode")
        plugin = self.registry.plugin_for_key(row["backend"])
        if plugin is None or not plugin.capabilities.resume:
            raise UnsupportedCapability("resume is not supported by this plugin")
        if not accepts_settings(plugin):
            raise UnsupportedCapability("mode change is not supported by this plugin")
        validate = getattr(plugin, "validate_resume_mode", None)
        if callable(validate):
            validate(mode)
        await self.stop(agent_id, client_id)
        await self.resume(agent_id, client_id, ResumeSettings(mode_id=mode))

    async def resume(
        self,
        agent_id: str,
        client_id: str,
        settings: ResumeSettings | None = None,
    ) -> None:
        row = self.resolve_session(agent_id)
        if row is None:
            raise KeyError(agent_id)
        system = self._authorize_write(agent_id, row, client_id)
        if not system:
            self._acquire_interactive_lease(row, client_id)
        lease_row = row
        try:
            plugin = self.registry.plugin_for_key(row["backend"])
            if plugin is None or not plugin.capabilities.resume:
                raise UnsupportedCapability("resume is not supported by this plugin")
            lock = self._send_locks.setdefault(
                self._session_lock_key(row), asyncio.Lock()
            )
            async with lock:
                row = self.store.get_session(row["id"])
                if row is None:
                    raise KeyError(agent_id)
                if row["lifecycle"] == "archived":
                    raise RuntimeError("cannot resume an archived session")
                already_live = await self._target(agent_id, None) is not None
                target = await self._target_for_send(agent_id, None, settings)
                if target is None:
                    raise RuntimeError("session could not be resumed")
            if already_live:
                return
            resumed_row, resumed_plugin, _, _ = target
            if resumed_row is None:
                raise RuntimeError("session could not be resumed")
            startup_spec = self._startup_specs.get(resumed_row["id"])
            if (
                startup_spec is not None
                and resumed_plugin.capabilities.persistent_process
            ):
                await self._prepare_resumed_startup(resumed_row, startup_spec)
        finally:
            if not system:
                self._release_interactive_lease(lease_row, client_id)

    async def _cancel_session_event_task(self, session_id: str) -> None:
        task = self._session_event_tasks.pop(session_id, None)
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _session_lock_key(self, row: Mapping[str, Any]) -> tuple[int, str]:
        ref = SessionRef(**json.loads(row["ref"]))
        plugin = self.registry.plugin_for_key(str(row["backend"]))
        return (id(plugin), ref.session_id)

    async def _wait_until_idle(
        self,
        row: dict[str, Any] | None,
        plugin: RunnerPlugin,
        ref: SessionRef,
    ) -> None:
        while True:
            if await self._live_idle(plugin, ref, row) == "idle":
                return
            await asyncio.sleep(0.05)

    async def respond(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        harness: str | None = None,
        *,
        client_id: str | None = None,
    ) -> str:
        row = self._session_row(session_id)
        system = self._authorize_write(session_id, row, client_id)
        if row is None:
            if harness is not None and harness not in self.registry.harnesses():
                return "unsupported"
            return await self._respond_unmanaged(
                session_id, request_id, decision, harness
            )
        if not system:
            self._acquire_interactive_lease(row, client_id)
        retain_lease = False

        async def respond_locked() -> str:
            lock = self._send_locks.setdefault(f"respond:{row['id']}", asyncio.Lock())
            async with lock:
                return await self._respond_locked(row, request_id, decision)

        try:
            result = await respond_locked()
            retain_lease = not system and result == "responded"
            return result
        finally:
            if not system and not retain_lease:
                self._release_interactive_lease(row, client_id)

    async def _respond_unmanaged(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        harness: str | None = None,
    ) -> str:
        candidates = (
            [self.registry.plugin_for(harness)]
            if harness is not None
            else list(self.registry.plugins())
        )
        candidates = [
            plugin
            for plugin in candidates
            if callable(getattr(plugin, "respond_permission", None))
            and plugin.capabilities.respond
        ]
        if len(candidates) != 1:
            return "unsupported" if not candidates else "ambiguous"
        plugin = candidates[0]
        provider = next(
            (
                key
                for key in sorted(self.registry.harnesses())
                if self.registry.plugin_for(key) is plugin
                and (harness is None or key == harness)
            ),
            None,
        )
        if provider is None:
            return "unsupported"
        try:
            responder = cast(
                "Callable[[SessionRef, str, str], Awaitable[None]]",
                plugin.respond_permission,
            )
            await responder(
                SessionRef(self.registry.provider_key(provider), session_id),
                request_id,
                decision,
            )
        except OSError, RuntimeError, TypeError, ValueError:
            return "failed"
        return "responded"

    async def _respond_locked(
        self, row: dict[str, Any], request_id: str, decision: str
    ) -> str:
        plugin = self.registry.plugin_for_key(row["backend"])
        if plugin is None or not plugin.capabilities.respond:
            return "unsupported"
        wait_id = approval_wait_id(row["id"], request_id)
        wait = self.store.get_wait(wait_id)
        if wait is None:
            return "stale"
        if wait["state"] != "pending":
            return response_for_wait(wait["decision"], decision)
        if row["id"] not in self._refs:
            return "stale"
        normalized_decision = normalize_decision(decision) or decision
        self.store.set_pending_wait_decision(wait_id, normalized_decision)
        try:
            await plugin.respond_permission(self._refs[row["id"]], request_id, decision)
        except Exception:  # noqa: BLE001 - expose plugin failures as outcomes
            self.store.set_pending_wait_decision(wait_id, None)
            return "failed"
        self.store.resolve_wait(wait_id, "resolved", normalized_decision)
        if (
            normalized_decision in {"approve", "deny", "ask_more", "expired"}
            and (row["id"], request_id) not in self._guard_approval_responses
        ):
            self.store.answer_decision_event(
                approval_wait_id(row["id"], request_id), normalized_decision
            )
        await self.record_event(
            row["id"],
            "permission_resolved",
            {
                "request_id": request_id,
                "decision": normalized_decision,
                "guarded": (row["id"], request_id) in self._guard_approval_responses,
            },
        )
        return "responded"

    def _reissue_bot_token(
        self, row: Mapping[str, Any], plugin: RunnerPlugin, ref: SessionRef
    ) -> None:
        setter = getattr(plugin, "set_env_overlay", None)
        if not callable(setter):
            return
        if row["role"] == BOT_ROLE and self.bot_token_issuer:
            setter(ref, dict(self.bot_token_issuer(row["id"])))
        elif is_bot_rooted(row.get("launched_by")) and self.bot_descendant_issuer:
            setter(ref, dict(self.bot_descendant_issuer(row["id"])))

    def _revoke_bot_token(self, session_id: str) -> None:
        if self.bot_token_revoker is not None:
            self.bot_token_revoker(session_id)

    def _is_bot_session(self, session_id: str) -> bool:
        row = self.store.get_session(session_id)
        return row is not None and row["role"] == BOT_ROLE

    async def _bot_permission(self, session_id: str, payload: dict[str, Any]) -> int:
        """Answer a bot permission request from the argv allowlist.

        There is no wait, card or guard, and the command is never stored.
        """
        decision = decide_request(payload)
        outcome = "approve" if decision.allow else "deny"
        plugin = self._bot_plugin(session_id)
        ref = self._refs.get(session_id)
        if plugin is not None and ref is not None:
            try:
                await plugin.respond_permission(ref, payload["request_id"], outcome)
            except Exception:
                logger.exception("could not answer bot permission request")
        seq = self.store.append_event(
            session_id,
            "activity",
            {
                "message": f"bot permission {outcome}: {decision.reason}",
                "tool": payload.get("tool"),
                "action": decision.action,
                "request_id": payload["request_id"],
            },
        )
        if self.bot_permission_sink is not None:
            self.bot_permission_sink(session_id, decision, str(payload.get("tool")))
        return seq

    def _bot_plugin(self, session_id: str) -> RunnerPlugin | None:
        row = self.store.get_session(session_id)
        return self.registry.plugin_for_key(row["backend"]) if row else None

    async def record_event(
        self, session_id: str, kind: str, payload: dict[str, Any]
    ) -> int:
        if kind in {"exit", "error"}:
            self._cancel_startup_diagnostic(session_id)
        elif is_agent_output(kind, payload):
            self._finish_startup_diagnostic(session_id)
        if (
            kind == "permission_requested"
            and isinstance(payload.get("request_id"), str)
            and self._is_bot_session(session_id)
        ):
            return await self._bot_permission(session_id, payload)
        if kind == "permission_requested" and isinstance(
            payload.get("request_id"), str
        ):
            request_id = payload["request_id"]
            seq = self.store.append_event_with_wait(
                session_id,
                kind,
                payload,
                wait_id=approval_wait_id(session_id, request_id),
                kind="approval",
                payload=payload,
            )
            self._record_permission_decision(session_id, request_id, payload)
            self._schedule_guard(session_id, request_id, payload)
        else:
            seq = self.store.append_event(session_id, kind, payload)
        if kind == "permission_resolved" and isinstance(payload.get("request_id"), str):
            decision = normalize_decision(payload.get("decision"))
            if decision is not None:
                self.store.resolve_wait(
                    approval_wait_id(session_id, payload["request_id"]),
                    "resolved",
                    decision,
                )
                if (
                    decision in {"approve", "deny", "ask_more", "expired"}
                    and (session_id, payload["request_id"])
                    not in self._guard_approval_responses
                    and not payload.get("guarded")
                    and not (
                        (
                            guard_verdict := self.store.guard_verdict_for(
                                session_id, payload["request_id"]
                            )
                        )
                        and guard_verdict.get("verdict") == "approve"
                    )
                ):
                    self.store.answer_decision_event(
                        approval_wait_id(session_id, payload["request_id"]),
                        decision,
                    )
        if kind == "status" and payload.get("status") in {"idle", "running", "error"}:
            value = str(payload["status"])
            self.store.update_session(session_id, status=value, idle_status=value)
            if value == "error" and payload.get("terminal") is True:
                self._unbind_address_binding(session_id)
        if kind == "session_end" and payload.get("terminal") is True:
            self._unbind_address_binding(session_id)
        if kind == "session_end" and payload.get("status") in {
            "completed",
            "interrupted",
        }:
            self.store.update_session(session_id, status="idle", idle_status="idle")
        self._schedule_idle_reap(session_id)
        return seq

    def _schedule_guard(
        self, session_id: str, request_id: str, payload: dict[str, Any]
    ) -> None:
        key = (session_id, request_id)
        if key in self._guard_tasks:
            return
        task = asyncio.create_task(self._run_guard(session_id, request_id, payload))
        self._guard_tasks[key] = task
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)
        task.add_done_callback(lambda _task: self._guard_tasks.pop(key, None))

    async def _run_guard(
        self, session_id: str, request_id: str, payload: dict[str, Any]
    ) -> None:
        try:
            role = load_config(config_path(), self.registry.known_harnesses()).guard()
        except Exception:
            logger.exception("could not load permission guard role")
            return
        if role is None:
            return
        kind = classify_request_kind(payload)
        audit_prompt = redact_prompt(payload)
        result = {
            "verdict": "escalate",
            "reason": "guard did not complete",
            "request_key": "other",
        }
        try:
            session = self.store.get_session(session_id)
            if session is None:
                result["reason"] = "permission session is missing"
                return
            workspace = self.store.get_workspace(session["workspace_id"])
            workspace_root = (
                (workspace.get("cwd") or workspace.get("worktree"))
                if workspace
                else None
            )
            allowed = guard_allowlist(
                self.store.decision_events(),
                revoked=self.store.revoked_guard_patterns(),
            )
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        evaluate_guard,
                        role,
                        kind,
                        payload,
                        workspace_root,
                        allowed,
                        self.registry,
                    ),
                    timeout=60,
                )
            except TimeoutError:
                result["reason"] = "guard timed out"
                return
            if not self.guard_enabled():
                result = result | {
                    "verdict": "escalate",
                    "reason": "guard disabled before it could decide",
                }
            if result["verdict"] == "approve":
                response_key = (session_id, request_id)
                self._guard_approval_responses.add(response_key)
                try:
                    outcome = await self.respond(session_id, request_id, "approve")
                finally:
                    self._guard_approval_responses.discard(response_key)
                if outcome != "responded":
                    result = result | {
                        "verdict": "escalate",
                        "reason": "permission approval could not be applied",
                    }
        except Exception:
            logger.exception("permission guard failed for %s", request_id)
            result = result | {"verdict": "escalate", "reason": "guard failed"}
        finally:
            try:
                self.store.record_guard_verdict(
                    session_id,
                    request_id,
                    result["request_key"],
                    kind,
                    audit_prompt,
                    result["verdict"],
                    result["reason"],
                    result["verdict"] == "escalate",
                )
            except Exception:
                logger.exception("could not record guard verdict for %s", request_id)
                try:
                    self.store.record_guard_verdict(
                        session_id,
                        request_id,
                        result["request_key"],
                        kind,
                        audit_prompt,
                        "escalate",
                        "guard verdict recording failed",
                        True,
                    )
                except Exception:
                    logger.exception("could not record escalation for %s", request_id)

    def _backfill_approval_waits(self) -> None:
        for session in self.store.sessions():
            events = self.store.events_after(session["id"], 0)
            pending: dict[str, dict[str, Any]] = {}
            for event in events:
                payload = event["payload"]
                request_id = payload.get("request_id")
                if not isinstance(request_id, str):
                    continue
                if event["kind"] == "permission_requested":
                    pending[request_id] = payload
                    self._record_permission_decision(session["id"], request_id, payload)
                elif event["kind"] == "permission_resolved":
                    pending.pop(request_id, None)
                    decision = normalize_decision(payload.get("decision"))
                    if (
                        decision in {"approve", "deny", "ask_more", "expired"}
                        and not payload.get("guarded")
                        and not (
                            (
                                guard_verdict := self.store.guard_verdict_for(
                                    session["id"], request_id
                                )
                            )
                            and guard_verdict.get("verdict") == "approve"
                        )
                    ):
                        self.store.answer_decision_event(
                            approval_wait_id(session["id"], request_id), decision
                        )
            for request_id, payload in pending.items():
                wait_id = approval_wait_id(session["id"], request_id)
                if self.store.get_wait(wait_id) is None:
                    self.store.create_wait(
                        wait_id, session["id"], "approval", payload=payload
                    )

    def _record_permission_decision(
        self, session_id: str, request_id: str, payload: dict[str, Any]
    ) -> None:
        decision_request_id = approval_wait_id(session_id, request_id)
        if self.store.has_decision_event(decision_request_id):
            return
        session = self.store.get_session(session_id)
        if session is None:
            return
        kind = classify_request_kind(payload)
        workspace = self.store.get_workspace(session["workspace_id"])
        workspace_root = (
            workspace.get("cwd") or workspace.get("worktree") if workspace else None
        )
        request_key = redact_request_key(kind, payload, workspace_root)
        approved_before = self.store.approved_before(request_key)
        self.store.record_decision_event(
            decision_request_id,
            plan=plan_from_branch(workspace["branch"] if workspace else None),
            role=session["role"],
            harness=session["harness"],
            model=session["model"],
            harness_mode=session["mode"],
            card_kind="permission",
            request_kind=kind,
            request_key=request_key,
            approved_before=approved_before,
        )

    async def _reconcile_approval_waits(
        self, session_id: str, plugin: Any, ref: SessionRef
    ) -> None:
        list_pending = getattr(plugin, "pending_permissions", None)
        if callable(list_pending):
            pending_call = cast(
                "Callable[[SessionRef], list[Any] | Awaitable[list[Any]]]",
                list_pending,
            )
            pending = pending_call(ref)
            if hasattr(pending, "__await__"):
                pending = await cast("Awaitable[list[Any]]", pending)
        else:
            list_agents = getattr(plugin, "list_agents", None)
            if not callable(list_agents):
                return
            list_agents_call = cast(
                "Callable[[], Awaitable[list[dict[str, Any]]]]", list_agents
            )
            agents = await list_agents_call()
            agent = next(
                (
                    item.get("agent", item)
                    for item in agents
                    if isinstance(item, dict)
                    and isinstance(item.get("agent", item), dict)
                    and item.get("agent", item).get("id") == ref.session_id
                ),
                None,
            )
            if agent is None:
                return
            pending = agent.get("pendingPermissions")
        if not isinstance(pending, list):
            return
        pending_ids = {
            item if isinstance(item, str) else item.get("request_id", item.get("id"))
            for item in pending
            if isinstance(item, (str, dict))
        }
        for wait in self.store.pending_waits():
            request_id = wait["payload"].get("request_id")
            if (
                wait["kind"] == "approval"
                and wait["session_id"] == session_id
                and request_id not in pending_ids
            ):
                self._expire_wait(wait, "expired")

    def _expire_wait(self, wait: dict[str, Any], decision: str) -> None:
        intended_decision = normalize_decision(wait.get("decision"))
        resolved_decision = intended_decision or decision
        state = "resolved" if intended_decision else "expired"
        if not self.store.resolve_wait(wait["wait_id"], state, resolved_decision):
            return
        if wait["kind"] == "approval":
            self.store.answer_decision_event(wait["wait_id"], resolved_decision)

    def _expire_unavailable_approvals(self) -> None:
        resumable = set(self._refs)
        for wait in self.store.pending_waits():
            if is_expired(wait["deadline"]) or (
                wait["kind"] == "approval" and wait["session_id"] not in resumable
            ):
                self._expire_wait(wait, "expired")

    async def _expire_due_waits_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            try:
                self._expire_unavailable_approvals()
                self._reschedule_pending_guards()
            except Exception:
                logger.exception("could not expire due runner waits")

    def _reschedule_pending_guards(self) -> None:
        if not self.guard_enabled():
            return
        for wait in self.store.waits_by_kind("approval", "pending"):
            request_id = wait["payload"].get("request_id")
            if not isinstance(request_id, str):
                continue
            if self.store.guard_verdict_for(wait["session_id"], request_id) is None:
                self._schedule_guard(wait["session_id"], request_id, wait["payload"])

    async def start_ipc(self, socket_path: Path) -> None:
        server_socket = create_server_socket(socket_path)
        self._ipc_server = await asyncio.start_unix_server(
            lambda reader, writer: serve_client(reader, writer, self._handle_ipc),
            sock=server_socket,
        )
        self._socket_path = socket_path

    async def _handle_ipc(self, message: dict[str, Any]) -> dict[str, Any]:
        operation = message.get("op")
        session_id = str(message.get("session_id", ""))
        if operation == "get_session":
            row = self.store.get_session(session_id)
            if row is None:
                raise KeyError(session_id)
            return row
        if operation == "events":
            return {
                "events": self.store.events_after(
                    session_id, int(message.get("after", 0))
                )
            }
        if operation == "waits":
            return {"waits": self.store.pending_waits()}
        if operation == "next_deadline":
            return {"next_deadline": self.store.earliest_deadline()}
        if operation == "send":
            outcome = await self.send(session_id, str(message["prompt"]))
            return {"outcome": outcome}
        if operation == "respond":
            outcome = await self.respond(
                session_id, str(message["request_id"]), str(message["decision"])
            )
            return {"outcome": outcome}
        raise ValueError("unsupported IPC operation")

    def approval_waits_for_mailbox(self) -> list[dict[str, Any]]:
        waits = [
            *self.store.waits_by_kind("approval", "pending"),
            *self.store.waits_by_kind("approval", "expired"),
        ]
        for wait in waits:
            session = self.store.get_session(wait["session_id"])
            ref = json.loads(session["ref"]) if session else {}
            wait["harness"] = (
                session.get("harness", session["backend"]) if session else None
            )
            wait["agent_title"] = session.get("role") if session else wait["session_id"]
            wait["remote_id"] = ref.get("session_id", wait["session_id"])
            wait["guard_enabled"] = self.guard_enabled()
            wait["guard_verdict"] = self.store.guard_verdict_for(
                wait["session_id"], str(wait["payload"].get("request_id", ""))
            )
        return waits

    def guard_enabled(self) -> bool:
        try:
            return (
                load_config(config_path(), self.registry.known_harnesses()).guard()
                is not None
            )
        except OSError, ValueError:
            return False

    async def shutdown(self) -> None:
        for session_id in tuple(self._startup_tasks):
            self._cancel_startup_diagnostic(session_id)
        idle_tasks = tuple(self._idle_reap_tasks.values())
        self._idle_reap_tasks.clear()
        for task in idle_tasks:
            task.cancel()
        if idle_tasks:
            await asyncio.gather(*idle_tasks, return_exceptions=True)
        for task in self._event_tasks:
            task.cancel()
        if self._event_tasks:
            await asyncio.gather(*self._event_tasks, return_exceptions=True)
        if self._ipc_server:
            self._ipc_server.close()
            await self._ipc_server.wait_closed()
        if self._socket_path:
            self._socket_path.unlink(missing_ok=True)
        closed_plugins: set[int] = set()
        for plugin in self.registry.plugins():
            if id(plugin) in closed_plugins:
                continue
            closed_plugins.add(id(plugin))
            await plugin.close()
        self.store.close()
