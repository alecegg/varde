"""HTTP surface for the orchestrator and mailbox dashboard."""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from math import inf
from pathlib import Path
from typing import Any, Never, cast
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from varde_data.config import load_data_config
from varde_data.decisions import decision_store_files
from varde_data.errors import Invalid
from varde_data.open import open_data
from varde_data.queue_paths import queue_migration_pending
from varde_data.views import classify_status
from varde_data.views.msg_status import runner_relay_alive
from varde_data.workitems import workitem_store_files

from varde_runner.agent_launch import launch_agent
from varde_runner.approvals import MergeApprovals
from varde_runner.bot_audit import BotAudit
from varde_runner.bot_constraints import ConstraintContext, load_bot_config
from varde_runner.bot_control import GOVERNOR, BotControl, ControlError
from varde_runner.bot_gateway import BotGateway
from varde_runner.bot_governor import load_caps
from varde_runner.bot_lifecycle import LifecycleHooks, ManagerBotLifecycle
from varde_runner.bot_route_policy import Classified, Kind, policy_for
from varde_runner.bot_tokens import BOT_ACTOR, BotIdentity, BotTokens
from varde_runner.bot_wake import ManagerBotWake
from varde_runner.cache import SingleFlightCache
from varde_runner.chat_delivery import ChatDelivery
from varde_runner.config import (
    MAIL_SOAK_SCHEDULE_ENV,
    ConfigError,
    config_path,
    default_toml,
    load_config,
    parse_config,
)
from varde_runner.decision_files import (
    dedupe_decision_file_items,
    project_decision_files,
)
from varde_runner.decisions import DecisionProjection, DecisionStore
from varde_runner.evidence import resolve_evidence_path
from varde_runner.instance_threads import InstanceThreads
from varde_runner.intake import InboxItem, InboxProjector
from varde_runner.job_registry import JOBS_BY_KEY
from varde_runner.job_store import fail_stale_runs, get_budget, open_job_store
from varde_runner.lease_keeper import run_expiry_ticks
from varde_runner.messages import recipient_matches_address
from varde_runner.open_decisions import OPEN_DECISION_KINDS, open_decision_items
from varde_runner.plan_reads import PlanReads
from varde_runner.plans_repository import shared_plans_repository
from varde_runner.plugins import child_environment
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.queue import parse_frontmatter
from varde_runner.relay import RelayWorker
from varde_runner.relay_cli import parse_relay_mode
from varde_runner.resource_writer import run_snapshot_ticks, snapshot_path
from varde_runner.review_job import (
    ReviewJob,
    execute_review_cli,
)
from varde_runner.review_job import (
    configured_schedule_time as configured_review_schedule_time,
)
from varde_runner.review_job import (
    configured_timeout_seconds as configured_review_timeout_seconds,
)
from varde_runner.soak_job import (
    SoakJob,
)
from varde_runner.soak_job import (
    configured_schedule_time as configured_soak_schedule_time,
)
from varde_runner.supervisor import Supervisor
from varde_runner.sweep_job import SweepJob, configured_schedule_time
from varde_runner.takeover import Takeover
from varde_runner.threads import open_needs_you_count
from varde_runner.user_credential import MergeApproverSecret, UserCredential
from varde_runner.varde_cli import VardeCLI
from varde_runner.wake import wake_agent_id
from varde_runner.web.activity import (
    plan_activity as _plan_activity,
)
from varde_runner.web.activity import (
    plan_id_for_address,
    waiting_plan_ids,
)
from varde_runner.web.agent_watch import create_agent_watch_route
from varde_runner.web.agents_route import agent_capabilities, create_agents_routes
from varde_runner.web.approvals_route import create_approval_routes
from varde_runner.web.approve_page import create_approve_page_routes
from varde_runner.web.bot_actions_route import create_bot_action_routes
from varde_runner.web.bot_audit_route import create_bot_audit_routes
from varde_runner.web.bot_route import create_bot_routes
from varde_runner.web.cache import (
    InboxStoreCache,
    watched_files_signature,
)
from varde_runner.web.card_metrics import CardMetricsRecorder
from varde_runner.web.chat_route import create_chat_routes
from varde_runner.web.guard_route import guard_routes
from varde_runner.web.identities_route import create_identities_routes
from varde_runner.web.instance_threads_route import (
    create_instance_threads_routes,
    plan_ids_from_working_dir,
)
from varde_runner.web.jobs_route import JobsController, create_jobs_routes
from varde_runner.web.metrics_route import decision_metrics
from varde_runner.web.newitem import create_newitem_routes, work_items_snapshot
from varde_runner.web.pairing_route import UserCredentialGate, create_pairing_routes
from varde_runner.web.pins import MAX_PINS_BODY_BYTES, read_pins, write_pins
from varde_runner.web.probe_route import probe_route
from varde_runner.web.queue import PlanReadSources, _plan_record, create_queue_routes
from varde_runner.web.queue_tasks_route import create_task_queue_routes
from varde_runner.web.registry import (
    NATIVE_HARNESSES,
    build_registry,
    paseo_model_catalog,
)
from varde_runner.web.role_queue_route import create_role_queue_routes
from varde_runner.web.role_queues_route import create_role_queues_route
from varde_runner.web.roles import create_roles_route
from varde_runner.web.runner_config_route import create_runner_config_routes
from varde_runner.web.runner_config_sdk_flip import create_sdk_flip_routes
from varde_runner.web.runner_config_toml_view import (
    create_runner_config_toml_view_route,
)
from varde_runner.web.runner_status_route import create_runner_status_routes
from varde_runner.web.settings import APP_ICON_OPTIONS, read_settings, write_settings
from varde_runner.web.takeover_route import create_takeover_routes
from varde_runner.web.threads_route import create_threads_routes
from varde_runner.workitems import WorkItemStore
from varde_runner.workspaces_config import configured_workspace_repos
from varde_runner.workspaces_service import WorkspacesService

_FILE_DECISION_LOCK = threading.Lock()

UI_DIR = Path(__file__).parent / "static" / "ui"
logger = logging.getLogger(__name__)
MODEL_CATALOG_TTL = 30
SNAPSHOT_CACHE_TTL = 3
ORCHESTRATOR_SNAPSHOT_TTL = 2
NEEDS_YOU_CACHE_TTL = 3
DASHBOARD_PREWARM_TIMEOUT = 15
DASHBOARD_PREWARM_START_DELAY = 1.0
SSE_REFRESH_INTERVAL = 15
SSE_KEEPALIVE_INTERVAL = 15
SSE_FILE_POLL_INTERVAL = 30.0
PLAN_DECISION_FILES_CACHE_TTL = 60.0
ORCHESTRATOR_LIVE_WINDOW = timedelta(minutes=30)
PUBLIC_AGENT_FIELDS = frozenset(
    {
        "id",
        "title",
        "status",
        "lastActivity",
        "lastActivityAt",
        "last_activity",
        "updatedAt",
    }
)
CONCLUDED_PLAN_STATUSES = frozenset(
    {"completed", "concluded", "cancelled", "abandoned"}
)
TERMINAL_PLAN_STATUSES = CONCLUDED_PLAN_STATUSES | {"finished", "done", "complete"}


def _slot_plan_is_terminal(plan: dict[str, Any]) -> bool:
    statuses = {
        str(plan.get(key) or "").lower() for key in ("status", "frontmatter_status")
    }
    return bool(statuses & TERMINAL_PLAN_STATUSES)


def _slot_plan_activity(plan: dict[str, Any]) -> float:
    value = plan.get("now_at") or plan.get("last_activity")
    if not isinstance(value, str):
        return -inf
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return -inf
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _slot_plan_has_tasks(plan: dict[str, Any]) -> bool:
    return int(plan.get("total") or 0) > 0 and not bool(plan.get("group"))


def _slot_plan_is_group(plan: dict[str, Any]) -> bool:
    return bool(plan.get("group"))


def _slot_plan_is_running(plan: dict[str, Any]) -> bool:
    status = str(plan.get("status") or plan.get("frontmatter_status") or "").lower()
    return status in {"running", "active"}


def _other_slot_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(plan.get("id") or ""),
        "title": str(plan.get("title") or ""),
        "status": str(plan.get("status") or plan.get("frontmatter_status") or ""),
        "done": plan.get("done", 0),
        "total": plan.get("total", 0),
    }


def select_slot_plans(
    plans: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Select a non-terminal primary and summarize its slot's other plans.

    Plans with tasks outrank group rows; taskless non-group children still outrank
    umbrellas. Running or active status then outranks activity time.
    """
    candidates = [plan for plan in plans if not _slot_plan_is_terminal(plan)]
    if not candidates:
        return None, []
    primary = max(
        candidates,
        key=lambda plan: (
            _slot_plan_has_tasks(plan),
            not _slot_plan_is_group(plan),
            _slot_plan_is_running(plan),
            _slot_plan_activity(plan),
            str(plan.get("id") or ""),
        ),
    )
    others = sorted(
        (plan for plan in candidates if plan is not primary),
        key=lambda plan: (
            not _slot_plan_has_tasks(plan),
            _slot_plan_is_group(plan),
            not _slot_plan_is_running(plan),
            -_slot_plan_activity(plan),
            str(plan.get("id") or ""),
        ),
    )
    return primary, [_other_slot_plan(plan) for plan in others]


def _public_orchestrators(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = snapshot.copy()
    result.pop("activity_agents", None)
    result["agents"] = [
        {key: value for key, value in agent.items() if key in PUBLIC_AGENT_FIELDS}
        for agent in result.get("agents", [])
        if isinstance(agent, dict)
    ]
    return result


async def _paseo_model_catalog() -> dict[str, Any]:
    return await paseo_model_catalog()


async def _registry_list(
    registry: PluginRegistry | None, method_name: str
) -> list[Any]:
    if registry is None:
        return []
    result: list[Any] = []
    for plugin in registry.plugins():
        method = getattr(plugin, method_name, None)
        if not callable(method):
            continue
        value = method()
        if inspect.isawaitable(value):
            value = await value
        if isinstance(value, list):
            result.extend(value)
    return result


async def _registry_model_catalog(registry: PluginRegistry | None) -> dict[str, Any]:
    if registry is None:
        return {}
    catalog: dict[str, Any] = {}
    for plugin in registry.plugins():
        method = getattr(plugin, "list_models", None)
        if callable(method):
            value = method()
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, dict):
                catalog.update(value)
    return catalog


def _work_item_lifecycle(
    data_dir: Path,
    on_started: Callable[[Any], None],
    plan_watch: Callable[[str], dict[str, Any]] | None = None,
    manager_wake: Callable[[dict[str, Any]], Awaitable[tuple[str, str]]] | None = None,
) -> tuple[
    Callable[[str, Path, str], Any],
    Callable[[Starlette], Any],
    Callable[[], PluginRegistry],
    Callable[[], Any],
]:
    supervisor_lock = asyncio.Lock()
    supervisor: Supervisor | None = None
    plugin_registry: PluginRegistry | None = None

    async def get_supervisor() -> Supervisor:
        nonlocal supervisor
        if supervisor is None:
            async with supervisor_lock:
                if supervisor is None:
                    candidate = Supervisor(data_dir / "sessions", get_registry())
                    await candidate.start()
                    supervisor = candidate
                    on_started(candidate)
        return supervisor

    def get_registry() -> PluginRegistry:
        nonlocal plugin_registry
        if plugin_registry is None:
            plugin_registry = build_registry()
        return plugin_registry

    async def start_work_item(item_id: str, notes_path: Path, project: str) -> Any:
        return await (await get_supervisor()).start_planner_session(
            item_id, notes_path, project
        )

    async def shutdown() -> None:
        if supervisor is not None:
            await supervisor.shutdown()
        elif plugin_registry is not None:
            for plugin in plugin_registry.plugins():
                close = getattr(plugin, "close", None)
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        relay_task: asyncio.Task[None] | None = None
        enabled = parse_relay_mode(os.environ.get("VARDE_RUNNER_RELAY")) is not None
        app.state.relay_enabled = enabled
        app.state.relay_worker = None
        try:
            if enabled:
                worker = RelayWorker(
                    None,
                    await get_supervisor(),
                    plan_watch=plan_watch,
                    manager_wake=manager_wake,
                )
                app.state.relay_worker = worker
                relay_task = asyncio.create_task(worker.run())
            yield
        finally:
            try:
                if relay_task is not None:
                    relay_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await relay_task
            except Exception:
                logger.exception("relay task failed during shutdown")
            finally:
                await shutdown()

    return start_work_item, lifespan, get_registry, get_supervisor


def _configured_models() -> dict[str, list[dict[str, str]]]:
    harness_to_provider = {
        "codex-app-server": "codex",
        "pi": "pi",
        "claude-sdk": "claude",
    }
    fallback: dict[str, dict[str, str]] = {
        key: {} for key in harness_to_provider.values()
    }
    source = config_path()
    config = load_config(source) if source.exists() else parse_config(default_toml())
    for role in config.roles.values():
        for model in (role, *role.fallback):
            provider = harness_to_provider.get(model.harness)
            if provider:
                fallback[provider][model.model] = model.model
            fallback.setdefault(model.harness, {})[model.model] = model.model
    return {
        provider: [{"id": model} for model in models]
        for provider, models in fallback.items()
    }


def read_context(message: dict[str, Any]) -> dict[str, Any]:
    notes = message.get("notes")
    if not isinstance(notes, str):
        return {}
    try:
        value = json.loads(Path(notes).read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _flatten_plans(rows: Any) -> list[dict[str, Any]]:
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return []
    flattened = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        flattened.append(row)
        flattened.extend(_flatten_plans(row.get("children", [])))
    return flattened


def _queue(plan: dict[str, Any], cli: Any) -> list[dict[str, Any]]:
    raw = plan.get("tasks", plan.get("queue"))
    if not isinstance(raw, list):
        plan_reads = getattr(cli, "plan_reads", None)
        if plan_reads is not None and plan_reads.enabled:
            raw = plan_reads.tasks_for_plan(str(plan.get("id", "")))
        else:
            task_reader = getattr(cli, "read_plan_tasks", None)
            try:
                if callable(task_reader):
                    raw = task_reader(str(plan.get("id", "")))
                else:
                    graph_reader = getattr(cli, "read_plan_graph", None)
                    if not callable(graph_reader):
                        return []
                    graph = graph_reader(str(plan.get("id", "")))
                    nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
                    raw = [
                        node
                        for node in nodes
                        if isinstance(node, dict)
                        and node.get("artifact_type") == "task"
                    ]
            except OSError, ValueError, RuntimeError, subprocess.SubprocessError:
                return []
    if not isinstance(raw, list):
        return []
    owner = plan.get("owner") or "unknown"
    return [
        {
            "id": task.get("id", "unknown"),
            "title": task.get("title", task.get("id", "Task")),
            "status": task.get("status", "unknown"),
            "status_at": task.get("status_at"),
            "owner": task.get("owner"),
            "owner_inherited": not bool(task.get("owner")) and owner != "unknown",
        }
        for task in raw
        if isinstance(task, dict)
    ]


def _message_age(plan: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    identifiers = {str(plan.get("id", ""))}
    if plan.get("owner"):
        identifiers.add(str(plan["owner"]))
    timestamps = []
    for message in messages:
        if not identifiers.intersection(
            {str(message.get("from", "")), str(message.get("to", ""))}
        ):
            continue
        try:
            timestamp = datetime.fromisoformat(str(message.get("ts", "")))
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        timestamps.append(timestamp)
    if not timestamps:
        return "unknown"
    seconds = max(0, int((datetime.now(UTC) - max(timestamps)).total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _plan_activity_fields(
    plan: dict[str, Any],
    agents: list[dict[str, Any]],
    orchestrator: dict[str, Any],
    open_questions: int = 0,
) -> dict[str, Any]:
    return _plan_activity(plan, agents, orchestrator, open_questions=open_questions)


def _message_time(message: dict[str, Any]) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(str(message.get("ts", "")))
    except ValueError:
        return None
    return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp


def _question_total(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return None


def _open_question_count(
    messages: list[dict[str, Any]],
    address: str,
    plan_id: str,
    plan: dict[str, Any],
    bindings: list[dict[str, Any]] | None = None,
) -> int:
    """Count unanswered decisions for one address and plan from message data."""
    question_total = _question_total(plan.get("questions"))
    if question_total is None:
        question_total = _question_total(plan.get("open_questions"))
    replies = [
        stamp
        for message in messages
        if isinstance(message, dict)
        and message.get("from") in {"main", "dashboard"}
        and recipient_matches_address(message.get("to"), address, bindings or [])
        and (stamp := _message_time(message)) is not None
    ]
    latest_reply = max(replies, default=None)
    count = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("kind") not in OPEN_DECISION_KINDS:
            continue
        sender = message.get("from")
        if sender == "varde-watch":
            if message.get("kind") not in {"needs-user", "needs-decision"}:
                continue
            if question_total == 0 or not _watch_notice_matches(
                message, address, plan_id
            ):
                continue
        elif sender != address:
            continue
        sent_at = _message_time(message)
        if latest_reply and sent_at and latest_reply >= sent_at:
            continue
        count += 1
    return count


def _watch_notice_matches(message: dict[str, Any], address: str, plan_id: str) -> bool:
    context = message.get("context")
    if isinstance(context, dict) and context.get("plan_id") == plan_id:
        return True
    text = str(message.get("text", ""))
    return bool(plan_id and plan_id in text or address and address in text)


def _messages_with_watch_context(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contextual = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("from") == "varde-watch" and not isinstance(
            message.get("context"), dict
        ):
            context = read_context(message)
            if context:
                contextual.append(message | {"context": context})
                continue
        contextual.append(message)
    return contextual


def _plan_row(
    address: str,
    context: dict[str, Any],
    cli: Any,
) -> dict[str, Any]:
    plans_by_slot = context["plans_by_slot"]
    watch_by_plan = context["watch_by_plan"]
    messages = context["messages"]
    bindings = context["bindings"]
    binding = context["binding"]
    agent = context["agent"]
    agents = context["agents"]
    row = plans_by_slot.get(address)
    if row is None:
        row = context["row_by_id"].get(address)
    plan_id = str(row.get("id")) if isinstance(row, dict) and row.get("id") else None
    joined = isinstance(row, dict)
    plan: dict[str, Any] = dict(row or {"id": address, "status": "unknown"})
    plan["_joinable"] = joined
    event = watch_by_plan.get(plan_id or address, {})
    wake = binding.get("wake_context")
    wake = wake if isinstance(wake, dict) else {}
    config = agent.get("config", {})
    config = config if isinstance(config, dict) else {}
    queue = _queue(plan, cli) if joined else []
    status = plan.get("status") or event.get("kind")
    assigned_backlog_is_live = (
        str(status or "").lower() == "backlog"
        and plan.get("assigned_to") == address
        and str(agent.get("status") or "").lower() in {"running", "active", "idle"}
    )
    if assigned_backlog_is_live:
        status = "running"
    awaiting_user = plan.get("awaiting_user") or event.get("awaiting_user")
    plan = plan | {"queue": queue, "status": status, "awaiting_user": awaiting_user}
    questions = _open_question_count(
        messages, address, plan_id or address, plan, bindings
    )
    activity = _plan_activity_fields(plan, agents, agent, questions)
    if assigned_backlog_is_live:
        activity["activity"] = "running"
    plan.pop("_joinable", None)
    return {
        **plan,
        **activity,
        "plan_joined": joined,
        "id": plan_id or address,
        "plan_id": plan_id or address,
        "address": address,
        "title": plan.get("title") if joined else f"orch {address}",
        "label": (plan.get("label") or plan.get("title"))
        if joined
        else f"orch {address}",
        "group_name": str(plan.get("group_name") or "") if joined else "",
        "owner": plan.get("owner")
        or (_plan_owner(plan_id, cli) if plan_id else None)
        or plan.get("assigned_to")
        or address,
        "queue": queue,
        "last_message_age": _message_age(plan, messages),
        "model": plan.get("model")
        or agent.get("model")
        or config.get("model")
        or "unknown",
        "worktree": plan.get("worktree") or agent.get("cwd") or "unknown",
        "last_event_at": plan.get("last_event_at") or "unknown",
        "agent_id": wake_agent_id(wake),
        "agent_status": agent.get("status"),
        "last_activity": _agent_activity(agent),
        "other_plans": context["other_plans_by_slot"].get(address, []),
    }


def _infrastructure_rows(
    bindings_by_address: dict[str, dict[str, Any]],
    agents_by_address: dict[str, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    result = []
    for address in ("main", "mailman"):
        binding = bindings_by_address.get(address)
        if binding is None:
            result.append(
                {
                    "address": address,
                    "paseo_id": None,
                    "title": address,
                    "status": "missing",
                    "stale": True,
                    "last_activity": None,
                }
            )
            continue
        agent = agents_by_address.get(address) or {}
        wake = binding.get("wake_context")
        wake = wake if isinstance(wake, dict) else {}
        status = agent.get("status", "unknown") if agent else "unknown"
        result.append(
            {
                "address": address,
                "paseo_id": wake_agent_id(wake),
                "title": agent.get("title") or address,
                "status": status,
                "stale": not bool(agent) and status != "alive",
                "last_activity": _agent_activity(agent),
            }
        )
    return result


def _apply_relay_liveness(
    infrastructure: list[dict[str, Any]], working: Path | None
) -> None:
    """Mark a bound mailman row stale when its relay is dead; relay death wins."""
    mailman = next(row for row in infrastructure if row["address"] == "mailman")
    if working is None or mailman["status"] == "missing":
        return
    snapshot = open_data(working, load_data_config()).addresses.relay_snapshot()
    state = {
        "current_mailman": snapshot.current_mailman,
        "events": [dict(event) for event in snapshot.events],
    }
    alive = runner_relay_alive(state, datetime.now(UTC))
    mailman["relay_alive"] = alive
    if not alive:
        mailman["status"] = "stale"
        mailman["stale"] = True


def _other_agents(
    agents: list[dict[str, Any]], bindings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    bound_ids = {
        str(wake_agent_id(item.get("wake_context", {})) or "")
        for item in bindings
        if isinstance(item.get("wake_context"), dict)
    }
    return [
        agent
        for item in agents
        if isinstance(item, dict)
        for agent in [item.get("agent", item)]
        if isinstance(agent, dict) and str(agent.get("id", "")) not in bound_ids
    ]


def _read_assigned_plans(
    cli: Any, plan_reads: PlanReads | None = None
) -> list[dict[str, Any]]:
    if plan_reads is not None and plan_reads.enabled:
        return plan_reads.assigned_plans()
    reader = getattr(cli, "read_assigned_plans", None)
    if not callable(reader):
        return []
    try:
        plans = reader()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("Could not read assigned plans: %s", exc)
        return []
    return plans if isinstance(plans, list) else []


def _plan_rows(  # noqa: PLR0913
    plan_status: Any,
    watch: Any,
    messages: list[dict[str, Any]],
    cli: Any,
    bindings: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    *,
    assigned_plans: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plan_status = plan_status if isinstance(plan_status, dict) else {}
    watch = watch if isinstance(watch, dict) else {}
    rows = _flatten_plans(plan_status.get("plans", []))
    agents_by_id = {
        str(agent["id"]): agent
        for item in agents
        if isinstance(item, dict)
        for agent in [item.get("agent", item)]
        if isinstance(agent, dict) and isinstance(agent.get("id"), str)
    }
    bindings = [item for item in bindings if isinstance(item, dict)]
    bindings_by_address = _bindings_by_address(bindings, agents_by_id)
    agents_by_address = {
        address: _bound_agent(binding, agents_by_id)
        for address, binding in bindings_by_address.items()
    }
    watch_by_plan = {
        event.get("plan"): event
        for event in watch.get("events", [])
        if isinstance(event, dict) and event.get("plan")
    }
    orchestrator_addresses = {
        address for address in bindings_by_address if address not in {"main", "mailman"}
    }
    row_by_id = {str(row.get("id")): row for row in rows if row.get("id")}
    for watch_plan in _flatten_plans(watch.get("plans", [])):
        plan_id = str(watch_plan.get("id") or "")
        if not plan_id:
            continue
        merged = dict(row_by_id.get(plan_id, {}))
        merged.update(
            {key: value for key, value in watch_plan.items() if value is not None}
        )
        row_by_id[plan_id] = merged
    status_watch_ids = set(row_by_id)
    for assigned_plan in _flatten_plans(assigned_plans):
        plan_id = str(assigned_plan.get("id") or "")
        if not plan_id:
            continue
        merged = {
            key: value for key, value in assigned_plan.items() if value is not None
        } | row_by_id.get(plan_id, {})
        row_by_id[plan_id] = merged
    ordered_rows = sorted(
        row_by_id.values(),
        key=lambda row: (
            bool(
                {
                    str(row.get("status") or "").lower(),
                    str(row.get("frontmatter_status") or "").lower(),
                }
                & TERMINAL_PLAN_STATUSES
            ),
            str(row.get("id") or "") not in status_watch_ids,
            str(row.get("id") or ""),
        ),
    )
    plans_by_slot = {}
    other_plans_by_slot = {}
    assigned_by_slot: dict[str, list[dict[str, Any]]] = {}
    for row in ordered_rows:
        assigned_to = row.get("assigned_to")
        if isinstance(assigned_to, str) and assigned_to:
            assigned_by_slot.setdefault(assigned_to, []).append(row)
    for address, assigned_rows in assigned_by_slot.items():
        primary, others = select_slot_plans(assigned_rows)
        if primary is None and assigned_rows:
            primary = assigned_rows[0]
        if primary is None:
            continue
        plans_by_slot[address] = primary
        other_plans_by_slot[address] = others
    messages = _messages_with_watch_context(messages)
    row_context = {
        "rows": rows,
        "row_by_id": row_by_id,
        "plans_by_slot": plans_by_slot,
        "other_plans_by_slot": other_plans_by_slot,
        "watch_by_plan": watch_by_plan,
        "messages": messages,
        "agents": agents,
        "bindings": bindings,
    }
    orchestrator_rows = [
        _plan_row(
            address,
            row_context
            | {
                "binding": bindings_by_address[address],
                "agent": agents_by_address.get(address) or {},
            },
            cli,
        )
        for address in sorted(orchestrator_addresses)
    ]
    result = []
    seen_plan_ids = set()
    for row in orchestrator_rows:
        plan_id = row.get("id")
        if plan_id in seen_plan_ids:
            continue
        seen_plan_ids.add(plan_id)
        result.append(row)
    infrastructure = _infrastructure_rows(bindings_by_address, agents_by_address)
    _apply_relay_liveness(infrastructure, _dashboard_working_dir(cli))
    return result, infrastructure, _other_agents(agents, bindings)


def _partition_orchestrators(
    rows: list[dict[str, Any]],
    working: Path | None,
    bindings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    slots = _slot_addresses(working) if working else set()
    retired = _retired_addresses(working) if working else set()
    now = datetime.now(UTC)
    bindings_by_address = {
        str(binding["address"]): binding
        for binding in bindings
        if isinstance(binding, dict) and isinstance(binding.get("address"), str)
    }
    live, past = [], []
    for row in rows:
        address = str(row.get("address", ""))
        plan_status = str(
            row.get("status") or row.get("frontmatter_status") or ""
        ).lower()
        joined_active = bool(row.get("plan_joined")) and plan_status not in {
            "completed",
            "concluded",
        }
        binding = bindings_by_address.get(address, {})
        seen = _binding_last_seen(binding)
        recently_bound = (
            seen != datetime.min.replace(tzinfo=UTC)
            and now - seen <= ORCHESTRATOR_LIVE_WINDOW
        )
        is_live = (
            address in slots
            or (joined_active and address not in retired)
            or recently_bound
        )
        row["live"] = is_live
        row["can_ask_status"] = is_live and row.get("activity") in {"idle", "stalled"}
        (live if is_live else past).append(row)
    return live, past


def _slot_addresses(working: Path) -> set[str]:
    addresses = open_data(working, load_data_config()).addresses
    return {name for slot in addresses.slots() for name in (slot.slot, *slot.aliases)}


def _retired_addresses(working: Path) -> set[str]:
    return set(
        open_data(working, load_data_config())
        .addresses.relay_snapshot()
        .retired.addresses
    )


def _bound_agent(
    binding: dict[str, Any], agents_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    wake = binding.get("wake_context")
    agent_id = wake_agent_id(wake)
    return agents_by_id.get(agent_id) if isinstance(agent_id, str) else None


def _bindings_by_address(
    bindings: list[dict[str, Any]], agents_by_id: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        address = binding.get("address")
        if isinstance(address, str):
            grouped.setdefault(address, []).append(binding)
    selected = {}
    for address, candidates in grouped.items():
        live = [
            binding for binding in candidates if _bound_agent(binding, agents_by_id)
        ]
        selected[address] = max(live or candidates, key=_binding_last_seen)
    return selected


def _binding_last_seen(binding: dict[str, Any]) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(binding.get("last_seen", "")))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp


def _plan_owner(plan_id: str, cli: Any) -> Any:
    plan_reads = getattr(cli, "plan_reads", None)
    if plan_reads is not None and plan_reads.enabled:
        return plan_reads.owner_for_plan(plan_id)
    reader = getattr(cli, "read_plan_summary", None)
    try:
        summary = reader(plan_id) if callable(reader) else {}
    except OSError, ValueError, RuntimeError, subprocess.SubprocessError:
        return None
    return summary.get("owner") if isinstance(summary, dict) else None


def _agent_activity(agent: dict[str, Any]) -> Any:
    return (
        agent.get("lastActivity")
        or agent.get("lastActivityAt")
        or agent.get("last_activity")
        or agent.get("updatedAt")
        or "unknown"
    )


def _option_text(option: Any) -> str:
    if isinstance(option, dict):
        return str(option.get("label") or option.get("id") or "")
    return str(option)


def _is_loopback_request(
    request: Request, bound_port: int, allowed_hosts: frozenset[str] = frozenset()
) -> bool:
    host = request.headers.get("host", "")
    parsed_host = urlsplit(f"//{host}")
    try:
        host_port = parsed_host.port
    except ValueError:
        return False
    hostname = parsed_host.hostname
    loopback = hostname in {"127.0.0.1", "localhost", "::1"} and host_port == bound_port
    allowed = hostname in allowed_hosts
    if not (loopback or allowed):
        return False
    if (
        (not allowed and host_port != bound_port)
        or parsed_host.username
        or parsed_host.password
    ):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    parsed_origin = urlsplit(origin)
    try:
        origin_port = parsed_origin.port
    except ValueError:
        return False
    return (
        (allowed or parsed_origin.scheme == request.url.scheme)
        and parsed_origin.hostname == parsed_host.hostname
        and (allowed or origin_port == bound_port)
        and parsed_origin.username is None
        and parsed_origin.password is None
        and parsed_origin.path in {"", "/"}
        and not parsed_origin.query
        and not parsed_origin.fragment
    )


class LocalRequestGuard(BaseHTTPMiddleware):
    def __init__(
        self, app, bound_port: int | None, allowed_hosts: frozenset[str] = frozenset()
    ) -> None:
        super().__init__(app)
        self.bound_port = bound_port
        self.allowed_hosts = allowed_hosts

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        server = request.scope.get("server")
        port = self.bound_port or (server[1] if server is not None else None)
        if (
            request.method == "POST"
            or request.url.path == "/events"
            or request.url.path.startswith("/api/")
            or request.url.path.startswith("/mailbox/")
        ) and not (
            port is not None and _is_loopback_request(request, port, self.allowed_hosts)
        ):
            return JSONResponse({"error": "invalid Host or Origin"}, status_code=403)
        return await call_next(request)


class RequestTimingMiddleware:
    """Record response timing without buffering streaming responses.

    ``response_bytes`` counts the body after compression, and Server-Timing
    ``dur`` measures time to response start.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        path = scope.get("path", "/")
        status = 500
        response_bytes = 0
        is_events = path == "/events" or (
            path.startswith("/api/agents/") and path.endswith("/watch")
        )
        logged = False

        def log(duration_ms: float) -> None:
            nonlocal logged
            if logged:
                return
            logged = True
            logger.info(
                "HTTP %s %s status=%d duration_ms=%.1f response_bytes=%d",
                scope.get("method", "GET"),
                path,
                status,
                duration_ms,
                response_bytes,
            )

        async def send_timed(message) -> None:
            nonlocal status, response_bytes
            if message["type"] == "http.response.start":
                status = message["status"]
                duration_ms = (time.perf_counter() - started) * 1000
                headers = list(message.get("headers", []))
                headers.append(
                    (b"server-timing", f"app;dur={duration_ms:.1f}".encode())
                )
                message = message | {"headers": headers}
                if is_events:
                    log(duration_ms)
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                log((time.perf_counter() - started) * 1000)

        try:
            await self.app(scope, receive, send_timed)
        except BaseException:
            if not logged:
                status = 500
                log((time.perf_counter() - started) * 1000)
            raise


@dataclass
class DashboardData:
    cli: Any
    projector: InboxProjector
    decisions: DecisionStore
    agent_reader: Callable[[], Any] | None
    model_reader: Callable[[], Any] | None = None
    projector_initialized: bool = False
    registry: PluginRegistry | None = None
    supervisor_getter: Callable[[], Any] | None = None
    cached_agents: list[dict[str, Any]] = field(default_factory=list)
    agents_loaded_at: float = 0.0
    agents_error: str | None = None
    agents_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    snapshot_refresh: asyncio.Task[dict[str, Any]] | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    snapshot_loaded_at: float = 0.0
    snapshot_plan_generation: int | None = None
    needs_you_snapshot: list[dict[str, Any]] = field(default_factory=list)
    needs_you_loaded_at: float = 0.0
    needs_you_refresh: asyncio.Task[list[dict[str, Any]]] | None = None
    model_catalog: dict[str, Any] = field(default_factory=dict)
    model_catalog_loaded_at: float = 0.0
    model_catalog_error: str | None = None
    planner_role_error: str | None = None
    planner_role_status: str | None = None
    model_catalog_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    inbox_cache: InboxStoreCache | None = None
    read_cache: SingleFlightCache = field(default_factory=SingleFlightCache)
    watched_roots: tuple[Path, ...] = ()
    evidence_roots: tuple[Path, ...] = ()
    agents_refresh: asyncio.Task[None] | None = None
    agents_initialized: bool = False
    prewarm_task: asyncio.Task[None] | None = None
    prewarm_failed: bool = False
    projection: asyncio.Task[list[InboxItem]] | None = None
    plan_reads: PlanReads | None = None
    queue_working_dir: Path | None = None

    def degraded_sources(self) -> list[str]:
        sources = [
            source
            for source in ("plan_status", "address_bindings")
            if self.read_cache.failing(source)
        ]
        if self.prewarm_failed:
            sources.append("startup_prewarm")
        working = getattr(self, "queue_working_dir", None) or _dashboard_working_dir(
            getattr(self, "cli", None)
        )
        if working is not None:
            try:
                if queue_migration_pending(working):
                    sources.append(
                        "queue migration pending: run varde plan queue merge-role-inbox"
                    )
            except Invalid as error:
                sources.append(f"queue migration status unavailable: {error}")
        if self.plan_reads is not None and (
            self.plan_reads.last_error is not None
            or self.plan_reads.refreshed_at is None
            or time.time() - self.plan_reads.refreshed_at > 3 * 2.0
        ):
            sources.append("plan_reads")
        return sorted(sources)

    async def respond(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        harness: str | None = None,
    ) -> str:
        if self.supervisor_getter is None:
            return "unsupported"
        supervisor = await self.supervisor_getter()
        return await supervisor.respond(session_id, request_id, decision, harness)

    async def role_models(self) -> dict[str, Any]:
        async with self.model_catalog_lock:
            if time.monotonic() - self.model_catalog_loaded_at >= MODEL_CATALOG_TTL:
                try:
                    loader = self.model_reader or (
                        lambda: _registry_model_catalog(self.registry)
                    )
                    value = loader()
                    if inspect.isawaitable(value):
                        value = await value
                    self.model_catalog = value if isinstance(value, dict) else {}
                    self.model_catalog_error = None
                except Exception as exc:  # noqa: BLE001 - keep editor usable during sidecar errors
                    self.model_catalog = {}
                    self.model_catalog_error = str(exc) or type(exc).__name__
                self.model_catalog_loaded_at = time.monotonic()
        configured_models = _configured_models()
        fallback = {
            provider: configured_models.get(provider, [])
            for provider in ("codex", "pi", "claude")
        }
        providers = {}
        catalog_error = self.model_catalog_error
        active_providers = (
            {
                self.registry.provider_key(harness)
                for harness in self.registry.harnesses()
            }
            if self.registry
            else set()
        )
        for provider in ("codex", "pi", "claude"):
            entry = self.model_catalog.get(provider, {})
            models = entry.get("models", []) if isinstance(entry, dict) else []
            providers[provider] = (
                [
                    model
                    for model in models
                    if isinstance(model, dict) and isinstance(model.get("id"), str)
                ]
                if isinstance(models, list)
                else []
            )
            if isinstance(entry, dict) and isinstance(entry.get("error"), str):
                catalog_error = catalog_error or f"{provider}: {entry['error']}"
            elif (
                provider in active_providers
                and not providers[provider]
                and not fallback[provider]
            ):
                catalog_error = catalog_error or f"{provider} model list is empty"
        return {
            "providers": providers,
            "fallback": fallback,
            "models_by_harness": (
                {
                    harness: configured_models.get(harness, [])
                    for harness in sorted(
                        set(self.registry.harnesses()) & NATIVE_HARNESSES
                    )
                }
                if self.registry
                else {}
            ),
            "harnesses": sorted(self.registry.harnesses()) if self.registry else [],
            "native_harnesses": (
                sorted(set(self.registry.harnesses()) & NATIVE_HARNESSES)
                if self.registry
                else []
            ),
            "providers_by_harness": (
                {
                    harness: self.registry.provider_key(harness)
                    for harness in self.registry.harnesses()
                }
                if self.registry
                else {}
            ),
            "error": catalog_error,
        }

    def inbox(self) -> list[dict[str, Any]]:
        with self.projector.db_lock:
            rows = self.projector.db.execute(
                "SELECT payload FROM inbox_projection ORDER BY rowid"
            ).fetchall()
        items = []
        messages = {
            str(message.get("id")): message
            for message in self.projector.last_messages
            if isinstance(message, dict) and message.get("id")
        }
        for row in rows:
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                continue
            message = messages.get(str(payload.get("msg_id", "")), {})
            if "body" not in payload:
                payload = {
                    **payload,
                    "subject": message.get("subject") or "",
                    "body": message.get("text") or message.get("body") or "",
                    "notes_text": (
                        self.projector._read_notes_text(message.get("notes"))
                        if payload.get("needs_context")
                        else ""
                    ),
                }
            decision = self.decisions.get_decision(str(payload.get("msg_id", "")))
            state = decision.get("state", "pending") if decision else "pending"
            sent_reply = _stored_mailbox_reply(
                self.decisions, str(payload.get("msg_id", ""))
            )
            items.append({**payload, **sent_reply, "state": state, "context": payload})
        for entry in self.cached_agents:
            agent = entry.get("agent") if isinstance(entry, dict) else None
            agent = agent if isinstance(agent, dict) else entry
            if not isinstance(agent, dict) or not isinstance(agent.get("id"), str):
                continue
            agent_id = agent["id"]
            pending = agent.get("pendingPermissions", [])
            if not isinstance(pending, list):
                continue
            for request in pending:
                if not isinstance(request, dict) or not isinstance(
                    request.get("id"), str
                ):
                    continue
                request_id = request["id"]
                msg_id = f"perm:{agent_id}:{request_id}"
                title = request.get("title")
                description = request.get("description")
                detail = request.get("detail")
                detail = detail if isinstance(detail, dict) else {}
                command = (
                    request.get("input", {}).get("command")
                    if isinstance(request.get("input"), dict)
                    else detail.get("command")
                )
                cwd = (
                    request.get("input", {}).get("cwd")
                    if isinstance(request.get("input"), dict)
                    else detail.get("cwd")
                )
                body = "\n".join(str(value) for value in (command, cwd) if value)
                self.decisions.project(
                    DecisionProjection(
                        source_id=request_id,
                        decision_id=msg_id,
                        kind="permission",
                        title=title if isinstance(title, str) else "Permission request",
                        body=body,
                        context={
                            "request_id": request_id,
                            "options": [
                                {"id": "allow", "kind": "allow", "label": "Allow"},
                                {"id": "deny", "kind": "deny", "label": "Deny"},
                            ],
                        },
                        source_agent=agent_id,
                    )
                )
                decision = self.decisions.get_decision(msg_id) or {}
                items.append(
                    {
                        "msg_id": msg_id,
                        "request_id": request_id,
                        "sender": agent_id,
                        "agent_title": agent.get("title", agent_id),
                        "kind": "permission",
                        "asked": title
                        if isinstance(title, str)
                        else "Permission request",
                        "why": description if isinstance(description, str) else "",
                        "body": body,
                        "options": [
                            {"id": "allow", "kind": "allow", "label": "Allow"},
                            {"id": "deny", "kind": "deny", "label": "Deny"},
                        ],
                        "state": decision.get("state", "pending"),
                        "ts": decision.get("created_at"),
                    }
                )
        return items

    async def mailbox_items(self) -> list[dict[str, Any]]:
        if not self.projector_initialized:
            await _shared_projection(self)
        await self.agents()
        items = list(self.read_cache.get_swr("mailbox", SNAPSHOT_CACHE_TTL, self.inbox))
        if self.supervisor_getter is None:
            return items
        supervisor = await self.supervisor_getter()
        waits = supervisor.approval_waits_for_mailbox()
        items = _filter_guard_permissions(items, waits)
        existing = {item.get("msg_id") for item in items}
        polled_permissions = {
            (item.get("sender"), item.get("request_id"))
            for item in items
            if item.get("kind") == "permission"
        }
        for wait in waits:
            request_id = wait["payload"].get("request_id")
            remote_id = wait.get("remote_id", wait["session_id"])
            verdict = wait.get("guard_verdict")
            if wait.get("guard_enabled") and (
                verdict is None or verdict.get("verdict") == "approve"
            ):
                continue
            msg_id = f"perm:{remote_id}:{request_id}"
            if msg_id in existing or (remote_id, request_id) in polled_permissions:
                continue
            expired = wait["state"] == "expired"
            title = wait["payload"].get("title")
            title = title if isinstance(title, str) else "Permission request"
            options = (
                []
                if expired
                else [
                    {"id": "allow", "kind": "allow", "label": "Allow"},
                    {"id": "deny", "kind": "deny", "label": "Deny"},
                ]
            )
            self.decisions.project(
                DecisionProjection(
                    source_id=request_id,
                    decision_id=msg_id,
                    kind="permission",
                    title=title,
                    body="",
                    context={"request_id": request_id, "options": options},
                    source_agent=wait["session_id"],
                )
            )
            decision = self.decisions.get_decision(msg_id) or {}
            items.append(
                {
                    "msg_id": msg_id,
                    "request_id": request_id,
                    "sender": wait["session_id"],
                    "agent_title": wait["agent_title"],
                    "harness": wait["harness"],
                    "kind": "permission",
                    "asked": title,
                    "why": "",
                    "body": "",
                    "options": options,
                    "state": "expired" if expired else decision.get("state", "pending"),
                    "ts": decision.get("created_at", wait.get("created_at")),
                    "guard_escalated": bool(
                        verdict and verdict.get("verdict") == "escalate"
                    ),
                }
            )
        return items

    async def open_mailbox_items(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        snapshot = await self.orchestrators()
        plans = [*snapshot.get("plans", []), *snapshot.get("past", [])]
        waiting_ids = waiting_plan_ids(plans)
        if self.inbox_cache is not None:
            store = await asyncio.to_thread(self.inbox_cache.read)
            cached_ids = {str(item.get("msg_id", "")) for item in items}
            items = [
                *items,
                *(
                    {
                        "msg_id": row["id"],
                        "sender": row.get("from"),
                        "kind": row["kind"],
                        "state": "pending",
                        "ts": row.get("ts"),
                    }
                    for row in store.messages
                    if row.get("id")
                    and row["id"] not in cached_ids
                    and row.get("kind") in OPEN_DECISION_KINDS
                ),
            ]
            bindings, plan_status = await asyncio.gather(
                asyncio.to_thread(self.address_bindings),
                asyncio.to_thread(_mailbox_plan_status, self),
            )
            plan_status = plan_status if isinstance(plan_status, dict) else {}
            bound_addresses = {
                str(row["address"])
                for row in bindings
                if isinstance(row, dict) and row.get("address")
            }
            closed_addresses = _closed_plan_ids(plan_status.get("plans", []))
            closed_addresses.update(store.concluded_addresses)
            closed_addresses.update(
                _bound_addresses_for_closed_plans(
                    plan_status.get("plans", []), bindings
                )
            )
            open_items = open_decision_items(
                items,
                store.messages,
                store.acknowledged_ids,
                bound_addresses,
                closed_addresses,
            )
            file_items = await asyncio.to_thread(
                _plan_decision_items,
                self,
                items,
                store.messages,
                store.acknowledged_ids,
            )
            file_items = [item for item in file_items if item.get("state") == "pending"]
            return [
                *_needs_you_items(open_items, plans, bindings, waiting_ids),
                *file_items,
            ]
        status_reader = getattr(self.cli, "read_message_status", None)
        concluded_reader = getattr(self.cli, "read_concluded_addresses", None)
        status_task = (
            asyncio.to_thread(
                _message_status,
                cast("Callable[[], dict[str, Any]]", status_reader),
            )
            if callable(status_reader)
            else asyncio.to_thread(dict)
        )
        concluded_task = (
            asyncio.to_thread(
                _concluded_address_list,
                cast("Callable[[], list[str]]", concluded_reader),
            )
            if callable(concluded_reader)
            else asyncio.to_thread(list)
        )
        status, bindings, plan_status, durable_concluded = await asyncio.gather(
            status_task,
            asyncio.to_thread(self.address_bindings),
            asyncio.to_thread(_mailbox_plan_status, self),
            concluded_task,
        )
        acknowledged_ids = {
            str(row["id"])
            for row in status.get("messages", [])
            if isinstance(row, dict) and row.get("acked") and row.get("id")
        }
        bound_addresses = {
            str(row["address"])
            for row in bindings
            if isinstance(row, dict) and row.get("address")
        }
        plan_status = plan_status if isinstance(plan_status, dict) else {}
        closed_addresses = _closed_plan_ids(plan_status.get("plans", []))
        closed_addresses.update(durable_concluded)
        closed_addresses.update(
            _bound_addresses_for_closed_plans(plan_status.get("plans", []), bindings)
        )
        open_items = open_decision_items(
            items,
            self.projector.last_messages,
            acknowledged_ids,
            bound_addresses,
            closed_addresses,
        )
        file_items = await asyncio.to_thread(
            _plan_decision_items,
            self,
            items,
            self.projector.last_messages,
            acknowledged_ids,
        )
        file_items = [item for item in file_items if item.get("state") == "pending"]
        return [
            *_needs_you_items(open_items, plans, bindings, waiting_ids),
            *file_items,
        ]

    def plan_status(self) -> dict[str, Any]:
        if self.plan_reads is not None and self.plan_reads.enabled:
            return self.plan_reads.status()

        def load() -> dict[str, Any]:
            reader = getattr(self.cli, "read_plan_status", None)
            value = reader() if callable(reader) else self.cli.read_plan()
            if not isinstance(value, dict):
                raise TypeError("plan status is unavailable")
            return value

        try:
            return self.read_cache.get_swr("plan_status", SNAPSHOT_CACHE_TTL, load)
        except Exception as exc:  # noqa: BLE001 - loader failures degrade this source
            logger.warning("Could not read plan status: %s", exc)
            return {}

    def plan_watch(self) -> dict[str, Any]:
        if self.plan_reads is not None and self.plan_reads.enabled:
            return self.plan_reads.watch()

        def load() -> dict[str, Any]:
            reader = getattr(self.cli, "read_plan_watch", None)
            value = reader() if callable(reader) else self.cli.read_plan()
            return value if isinstance(value, dict) else {}

        return self.read_cache.get_swr("plan_watch", SNAPSHOT_CACHE_TTL, load)

    async def waiting_plans(self) -> list[dict[str, Any]]:
        snapshot = await self.orchestrators()
        return [*snapshot.get("plans", []), *snapshot.get("past", [])]

    def address_bindings(self) -> list[dict[str, Any]]:
        if self.plan_reads is not None and self.plan_reads.enabled:
            return self.plan_reads.bindings()

        def load() -> list[dict[str, Any]]:
            reader = getattr(self.cli, "read_address_bindings", None)
            if not callable(reader):
                return []
            value = reader()
            return value if isinstance(value, list) else []

        return self.read_cache.get_swr("address_bindings", SNAPSHOT_CACHE_TTL, load)

    def queue_inputs(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return self.plan_status(), self.address_bindings()

    async def agents(self) -> list[dict[str, Any]]:
        async with self.agents_lock:
            if not self.agents_initialized:
                await self._refresh_agents()
                return self.cached_agents
            if time.monotonic() - self.agents_loaded_at < 5:
                return self.cached_agents
            if self.agents_refresh is None or self.agents_refresh.done():
                self.agents_refresh = asyncio.create_task(self._refresh_agents())
            return self.cached_agents

    async def _refresh_agents(self) -> None:
        try:

            async def refresh() -> list[dict[str, Any]]:
                if self.agent_reader is not None:
                    value = self.agent_reader()
                    if inspect.isawaitable(value):
                        value = await value
                    return value if isinstance(value, list) else []
                return await _registry_list(self.registry, "list_agents")

            self.cached_agents = await asyncio.wait_for(refresh(), timeout=20)
            self.agents_error = None
        except Exception as exc:  # noqa: BLE001 - sidecar errors must not break the dashboard
            self.agents_error = str(exc) or type(exc).__name__
        finally:
            self.agents_loaded_at = time.monotonic()
            self.agents_initialized = True

    async def orchestrators(self) -> dict[str, Any]:
        """Serve the last snapshot while a single shared refresh rebuilds it.

        A cold or invalidated snapshot waits for the shared refresh; an aged one
        is returned at once so slow plan reads cannot queue up request after request.
        """
        if not self.projector_initialized:
            await _shared_projection(self)
        plan_generation = (
            self.plan_reads.generation_value()
            if self.plan_reads is not None and self.plan_reads.enabled
            else None
        )
        generation_changed = (
            plan_generation is not None
            and self.snapshot_plan_generation != plan_generation
        )
        age = time.monotonic() - self.snapshot_loaded_at
        if (
            self.snapshot_loaded_at
            and not generation_changed
            and age < ORCHESTRATOR_SNAPSHOT_TTL
        ):
            return self.snapshot
        if generation_changed:
            self.snapshot_loaded_at = 0.0
        refresh = self._snapshot_refresh_task()
        if self.snapshot_loaded_at:
            return self.snapshot
        if (
            self.plan_reads is not None
            and self.plan_reads.enabled
            and not self.plan_reads.ready
        ):
            return _empty_orchestrator_snapshot()
        return await asyncio.shield(refresh)

    async def cached_needs_you(self) -> list[dict[str, Any]]:
        refresh_due = time.monotonic() - self.needs_you_loaded_at >= NEEDS_YOU_CACHE_TTL
        refresh_idle = self.needs_you_refresh is None or self.needs_you_refresh.done()
        if refresh_due and refresh_idle:
            self.needs_you_refresh = asyncio.create_task(
                self.refresh_needs_you_snapshot()
            )
        if not self.needs_you_loaded_at and self.needs_you_refresh is not None:
            await asyncio.shield(self.needs_you_refresh)
        return self.needs_you_snapshot

    async def request_needs_you(self) -> list[dict[str, Any]]:
        if self.plan_reads is not None and self.plan_reads.enabled:
            return await self.cached_needs_you()
        return await self.needs_you_threads()

    async def refresh_needs_you_snapshot(self) -> list[dict[str, Any]]:
        try:
            self.needs_you_snapshot = await self.needs_you_threads()
        except Exception:
            logger.exception("Could not refresh needs-you snapshot")
        finally:
            self.needs_you_loaded_at = time.monotonic()
        return self.needs_you_snapshot

    def _snapshot_refresh_task(self) -> asyncio.Task[dict[str, Any]]:
        if self.snapshot_refresh is None or self.snapshot_refresh.done():
            self.snapshot_refresh = asyncio.create_task(self._build_snapshot())
            self.snapshot_refresh.add_done_callback(_log_snapshot_failure)
        return self.snapshot_refresh

    async def _build_snapshot(self) -> dict[str, Any]:
        (
            agents,
            plan_status,
            watch,
            assigned_plans,
            bindings,
        ) = await asyncio.gather(
            self.agents(),
            asyncio.to_thread(self.plan_status),
            asyncio.to_thread(self.plan_watch),
            asyncio.to_thread(_read_assigned_plans, self.cli, self.plan_reads),
            asyncio.to_thread(self.address_bindings),
        )
        plans, infrastructure, other_agents = await asyncio.to_thread(
            _plan_rows,
            plan_status,
            watch,
            self.projector.last_messages,
            self.cli,
            bindings,
            agents,
            assigned_plans=assigned_plans,
        )
        if self.planner_role_error is not None:
            infrastructure.append(
                {
                    "address": "planner",
                    "paseo_id": None,
                    "title": "Planner role",
                    "status": self.planner_role_status,
                    "stale": True,
                    "last_activity": None,
                    "reason": self.planner_role_error,
                }
            )
        plans, past = _partition_orchestrators(
            plans, _dashboard_working_dir(self.cli), bindings
        )
        self.snapshot = {
            "plans": plans,
            "past": past,
            "infrastructure": infrastructure,
            "agents": other_agents,
            "activity_agents": agents,
            "agents_error": self.agents_error,
        }
        self.snapshot_loaded_at = time.monotonic()
        self.snapshot_plan_generation = (
            self.plan_reads.generation_value()
            if self.plan_reads is not None and self.plan_reads.enabled
            else None
        )
        return self.snapshot

    async def mailbox_threads(self) -> list[dict[str, Any]]:
        from varde_runner.threads import group_threads, is_user_facing_message

        items = await _projected_mailbox_items(self)
        messages = {
            str(message.get("id")): message
            for message in self.projector.last_messages
            if isinstance(message, dict) and message.get("id")
        }
        items = [
            item
            for item in items
            if is_user_facing_message(messages.get(str(item.get("msg_id")), item))
        ]
        open_items = await self.open_mailbox_items(items)
        snapshot = await self.orchestrators()
        plans = [*snapshot.get("plans", []), *snapshot.get("past", [])]
        bindings = await asyncio.to_thread(self.address_bindings)
        linked_items = []
        for item in items:
            plan_id = plan_id_for_address(str(item.get("sender", "")), plans, bindings)
            linked_items.append(item | {"plan_id": plan_id or item.get("plan_id")})
        items = linked_items
        permissions = [
            item
            for item in items
            if item.get("kind") == "permission" and item.get("state") == "pending"
        ]
        open_ids = {str(item.get("msg_id")) for item in [*open_items, *permissions]}
        threads = group_threads(items, open_ids)
        titles = {
            plan_id: str(plan.get("label") or plan.get("title"))
            for plan in plans
            if isinstance(plan_id := plan.get("id"), str)
            and plan_id
            and (plan.get("label") or plan.get("title"))
        }
        return [
            thread
            | {
                "plan_title": titles.get(plan_id, "")
                if isinstance(plan_id := thread.get("plan_id"), str)
                else ""
            }
            for thread in threads
        ]

    async def needs_you_threads(self) -> list[dict[str, Any]]:
        return [
            thread for thread in await self.mailbox_threads() if thread["open_count"]
        ]

    @staticmethod
    def include_needs_you(
        snapshot: dict[str, Any], threads: list[dict[str, Any]]
    ) -> dict[str, Any]:
        needs_you_ids = {
            thread["plan_id"] for thread in threads if thread.get("plan_id")
        }
        plans = [
            plan
            | {
                "activity": "waiting"
                if plan.get("id") in needs_you_ids
                else (
                    "idle"
                    if plan.get("activity") == "waiting"
                    else plan.get("activity")
                )
            }
            for plan in snapshot.get("plans", [])
        ]
        return snapshot | {
            "plans": plans,
            "needs_you": threads,
            "needs_you_count": open_needs_you_count(threads),
        }


MAILBOX_PAGE_SIZE = 50
MAILBOX_MAX_PAGE_SIZE = 200
MAILBOX_IDS_MAX = 100


def _mailbox_payload(
    items: list[dict[str, Any]],
    *,
    limit: int = MAILBOX_PAGE_SIZE,
    before: str | None = None,
    ids: set[str] | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    displayed_kinds = OPEN_DECISION_KINDS | {"permission", "info-failure"}
    for item in items:
        key = f"{item['kind']}:{item['state']}"
        counts[key] = counts.get(key, 0) + 1
    displayed = sorted(
        (item for item in items if item["kind"] in displayed_kinds),
        key=_mailbox_position,
        reverse=True,
    )
    total = len(displayed)
    if before is not None:
        cursor_position = _decode_mailbox_cursor(before)
        displayed = [
            item for item in displayed if _mailbox_position(item) < cursor_position
        ]
    if ids is not None:
        page = [item for item in displayed if item.get("msg_id") in ids]
        next_before = None
    else:
        page = displayed[:limit]
        next_before = (
            _encode_mailbox_cursor(page[-1])
            if len(displayed) > len(page) and page
            else None
        )
    return {
        "counts_by_kind_state": counts,
        "all": page,
        "total": total,
        "next_before": next_before,
        "open": [
            item
            for item in items
            if item["state"] == "pending" and item["kind"] in OPEN_DECISION_KINDS
        ],
        "permissions": [
            {**item, "mailbox_open": True}
            for item in items
            if item["state"] == "pending" and item["kind"] == "permission"
        ],
        "resolved": [
            _mailbox_resolved_summary(item)
            for item in page
            if item["state"] != "pending"
        ],
    }


def _filter_guard_permissions(
    items: list[dict[str, Any]], waits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Hide guarded pending permissions until escalation, and mark those escalated."""
    visibility = {
        (
            str(wait.get("remote_id", wait["session_id"])),
            str(wait["payload"].get("request_id", "")),
        ): wait
        for wait in waits
    }
    result = []
    for item in items:
        visible_item = item
        wait = visibility.get(
            (str(item.get("sender", "")), str(item.get("request_id", "")))
        )
        verdict = wait.get("guard_verdict") if wait else None
        if item.get("kind") == "permission" and wait and wait.get("guard_enabled"):
            if verdict is None or verdict.get("verdict") == "approve":
                continue
            if verdict.get("verdict") == "escalate":
                visible_item = item | {"guard_escalated": True}
        result.append(visible_item)
    return result


def _mailbox_resolved_summary(item: dict[str, Any]) -> dict[str, Any]:
    fields = ("msg_id", "state")
    return {key: item[key] for key in fields if key in item}


def _mailbox_position(item: dict[str, Any]) -> tuple[datetime, str]:
    timestamp = item.get("ts")
    if not isinstance(timestamp, str):
        return datetime.min.replace(tzinfo=UTC), str(item.get("msg_id") or "")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        parsed = datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC), str(item.get("msg_id") or "")


def _encode_mailbox_cursor(item: dict[str, Any]) -> str:
    value = json.dumps([item.get("ts"), str(item.get("msg_id") or "")]).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_mailbox_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        encoded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        value = json.loads(decoded)
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ValueError("invalid mailbox cursor") from exc
    if (
        not isinstance(value, list)
        or len(value) != 2
        or (value[0] is not None and not isinstance(value[0], str))
        or not isinstance(value[1], str)
    ):
        raise ValueError("invalid mailbox cursor")
    return _mailbox_position({"ts": value[0], "msg_id": value[1]})


def _mailbox_summary(item: dict[str, Any], open_ids: set[str]) -> dict[str, Any]:
    fields = (
        "msg_id",
        "request_id",
        "kind",
        "type",
        "state",
        "ts",
        "sender",
        "title",
        "asked",
        "subject",
    )
    return {
        **{key: item[key] for key in fields if key in item},
        "mailbox_open": item.get("msg_id") in open_ids,
        "summary_only": True,
    }


def _stored_mailbox_reply(decisions: DecisionStore, decision_id: str) -> dict[str, str]:
    reply = decisions.latest_delivered_reply(decision_id)
    if reply is None:
        return {}
    return {"reply": reply.body, "sent_at": reply.sent_at}


def _refresh_mailbox(dashboard: DashboardData) -> list[dict[str, Any]]:
    return dashboard.read_cache.get("mailbox", SNAPSHOT_CACHE_TTL, dashboard.inbox)


def _latest_mail_soak_report(reports_dir: Path) -> dict[str, Any] | None:
    dated_reports = []
    try:
        report_paths = list(reports_dir.glob("*.json"))
    except OSError:
        return None
    for path in report_paths:
        try:
            if date.fromisoformat(path.stem).isoformat() == path.stem:
                dated_reports.append(path)
        except ValueError:
            continue
    for path in sorted(dated_reports, key=lambda item: item.stem, reverse=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, ValueError:
            continue
        if isinstance(report, dict):
            return report
    return None


def _log_snapshot_failure(task: asyncio.Task[dict[str, Any]]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Orchestrator snapshot refresh failed: %s", task.exception())


async def _prewarm_dashboard(
    dashboard: DashboardData, queue_prewarm: Callable[[], Any] | None = None
) -> None:
    warmers = [
        asyncio.to_thread(dashboard.projector.project),
        dashboard.mailbox_items(),
        dashboard.orchestrators(),
        dashboard.refresh_needs_you_snapshot(),
    ]
    if queue_prewarm is not None:
        warmers.append(queue_prewarm())
    tasks = [asyncio.ensure_future(warmer) for warmer in warmers]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _run_prewarm(
    dashboard: DashboardData, queue_prewarm: Callable[[], Any] | None
) -> None:
    """Warm caches in the background; a failure only marks the dashboard degraded."""
    try:
        await asyncio.sleep(DASHBOARD_PREWARM_START_DELAY)
        await asyncio.wait_for(
            _prewarm_dashboard(dashboard, queue_prewarm),
            timeout=DASHBOARD_PREWARM_TIMEOUT,
        )
    except TimeoutError:
        dashboard.prewarm_failed = True
        logger.warning(
            "Dashboard cache prewarm timed out after %.1f seconds",
            DASHBOARD_PREWARM_TIMEOUT,
        )
    except Exception:
        dashboard.prewarm_failed = True
        logger.exception("Dashboard cache prewarm failed")


def _dashboard_lifespan(
    base_lifespan: Callable[[Starlette], Any],
    dashboard: DashboardData,
    get_registry: Callable[[], PluginRegistry],
    get_supervisor: Callable[[], Any],
    queue_prewarm: Callable[[], Any] | None = None,
) -> Callable[[Starlette], Any]:
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if dashboard.plan_reads is not None:
            dashboard.plan_reads.start()
        try:
            async with base_lifespan(app):
                app.state.registry = get_registry()
                original_agents_reader = dashboard.agent_reader
                if original_agents_reader is None:
                    dashboard.agent_reader = lambda: _registry_list(
                        dashboard.registry, "list_agents"
                    )
                dashboard.prewarm_task = asyncio.create_task(
                    _run_prewarm(dashboard, queue_prewarm)
                )
                try:
                    yield
                finally:
                    refresh = dashboard.snapshot_refresh
                    dashboard.prewarm_task.cancel()
                    if refresh is not None:
                        refresh.cancel()
                    await asyncio.gather(dashboard.prewarm_task, return_exceptions=True)
                    if refresh is not None:
                        await asyncio.gather(refresh, return_exceptions=True)
                    dashboard.agent_reader = original_agents_reader
        finally:
            if dashboard.plan_reads is not None:
                await asyncio.to_thread(dashboard.plan_reads.stop)

    return lifespan


async def _refresh_mailbox_after_action(dashboard: DashboardData, action: str) -> None:
    try:
        await asyncio.to_thread(_refresh_mailbox, dashboard)
    except Exception:
        logger.exception("Post-%s mailbox refresh failed", action)


async def _shared_projection(dashboard: DashboardData) -> list[InboxItem]:
    """Join a running projection instead of queueing another behind db_lock."""
    if dashboard.projection is None or dashboard.projection.done():
        dashboard.projection = asyncio.create_task(
            asyncio.to_thread(dashboard.projector.project)
        )
    projected = await asyncio.shield(dashboard.projection)
    dashboard.projector_initialized = True
    return projected


async def _projected_mailbox_items(dashboard: DashboardData) -> list[dict[str, Any]]:
    projected = await _shared_projection(dashboard)
    cached = dashboard.read_cache.peek("mailbox")
    projected_ids = {row.msg_id for row in projected}
    cached_ids = {row.get("msg_id") for row in cached or []}
    if cached is not None and projected_ids != cached_ids:
        dashboard.read_cache.invalidate("mailbox", refresh=False)
        dashboard.snapshot = {}
        dashboard.snapshot_loaded_at = 0
        items = await asyncio.to_thread(_refresh_mailbox, dashboard)
    else:
        items = await dashboard.mailbox_items()
    acknowledged_ids: set[str] = set()
    messages = dashboard.projector.last_messages
    if dashboard.inbox_cache is not None:
        inbox = await asyncio.to_thread(dashboard.inbox_cache.read)
        acknowledged_ids = inbox.acknowledged_ids
        messages = inbox.messages
    file_items = await asyncio.to_thread(
        _plan_decision_items, dashboard, items, messages, acknowledged_ids
    )
    return [*items, *file_items]


def _plan_decision_items(
    dashboard: DashboardData,
    mail_items: list[dict[str, Any]],
    mail_messages: list[dict[str, Any]],
    acknowledged_ids: set[str],
) -> list[dict[str, Any]]:
    working = _dashboard_working_dir(dashboard.cli)
    if working is None:
        return []

    def load() -> list[dict[str, Any]]:
        records = (
            shared_plans_repository(working, getattr(dashboard.cli, "env", None))
            .list()
            .records
        )
        plans = []
        for record in records:
            if record.artifact_type != "plan":
                continue
            fields = parse_frontmatter(record.raw.decode("utf-8"))
            if classify_status(fields.get("status", "")) == "terminal":
                continue
            owner = fields.get("assigned_to")
            if not owner:
                continue
            plan_path = Path(record.path)
            plans.append(
                {
                    "id": fields.get("id") or plan_path.parent.name,
                    "status": fields.get("status", ""),
                    "assigned_to": owner,
                    "directory": plan_path.parent,
                }
            )
        return project_decision_files(plans, include_answered=True)

    cached_items = dashboard.read_cache.get_swr(
        f"plan-decision-files:{working}", PLAN_DECISION_FILES_CACHE_TTL, load
    )
    return dedupe_decision_file_items(
        cached_items, mail_items, mail_messages, acknowledged_ids
    )


def _message_status(reader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        value = reader()
    except OSError, ValueError, RuntimeError, subprocess.SubprocessError:
        return {}
    return value if isinstance(value, dict) else {}


def _concluded_address_list(reader: Callable[[], list[str]]) -> list[str]:
    try:
        value = reader()
    except OSError, ValueError, RuntimeError, subprocess.SubprocessError:
        return []
    if not isinstance(value, list):
        return []
    return [address for address in value if isinstance(address, str)]


def _mailbox_plan_status(dashboard: DashboardData) -> dict[str, Any]:
    try:
        value = dashboard.plan_status()
    except OSError, ValueError, RuntimeError, subprocess.SubprocessError:
        return {}
    return value if isinstance(value, dict) else {}


def _dashboard_working_dir(cli: Any) -> Path | None:
    configured = getattr(cli, "env", {}).get("VARDE_WORKING_DIR")
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser().resolve()
    working_dir = getattr(cli, "cwd", None)
    return working_dir.expanduser().resolve() if isinstance(working_dir, Path) else None


def _projector_plan_reader(
    cli: Any, dashboard_ref: dict[str, DashboardData]
) -> Callable[[], dict[str, Any]]:
    def read_plan() -> dict[str, Any]:
        dashboard = dashboard_ref.get("dashboard")
        if dashboard is None:
            # create_app's first projection reads messages only; the slow plan
            # watch runs in the background prewarm instead of before the port opens.
            return {"events": []}
        return dashboard.plan_watch()

    return read_plan


def _sse_refresh_due(
    files: tuple[tuple[str, int, int, int, int], ...],
    previous_files: tuple[tuple[str, int, int, int, int], ...] | None,
    last_full_refresh: float,
    now: float,
) -> bool:
    return files != previous_files or now - last_full_refresh >= SSE_REFRESH_INTERVAL


_EVENT_TOPIC_FIELDS = {
    "orchestrators": (
        "plans",
        "past",
        "infrastructure",
        "agents",
        "agents_error",
        "needs_you",
    ),
    "mailbox": ("items", "mailbox", "permissions"),
    "work_items": ("work_items",),
}
_EVENT_TOPICS = ("orchestrators", "mailbox", "work_items", "queue")
_EVENT_CHURN_FIELDS = {
    "plans": frozenset({"idle_for", "last_message_age", "last_activity"}),
    "past": frozenset({"idle_for", "last_message_age", "last_activity"}),
    "infrastructure": frozenset({"last_activity"}),
    "agents": frozenset(
        {"lastActivity", "lastActivityAt", "last_activity", "updatedAt"}
    ),
}


def _empty_orchestrator_snapshot() -> dict[str, Any]:
    return {
        "plans": [],
        "past": [],
        "infrastructure": [],
        "agents": [],
        "activity_agents": [],
        "agents_error": None,
    }


def _event_hash_projection(topic: str, value: Any) -> Any:
    fields = _EVENT_CHURN_FIELDS.get(topic, frozenset())
    if isinstance(value, list):
        return [_event_hash_projection(topic, item) for item in value]
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key not in fields}
    return value


def _event_topic_hashes(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        topic: sha256(
            json.dumps(
                {
                    field: _event_hash_projection(field, snapshot.get(field))
                    for field in fields
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        for topic, fields in _EVENT_TOPIC_FIELDS.items()
    }


def _event_update_frame(
    snapshot: dict[str, Any], previous_hashes: dict[str, str] | None
) -> tuple[bytes | None, dict[str, str]]:
    hashes = _event_topic_hashes(snapshot)
    if previous_hashes is None:
        changed = list(_EVENT_TOPICS)
    else:
        changed = [
            topic
            for topic, digest in hashes.items()
            if previous_hashes.get(topic) != digest
        ]
        if "orchestrators" in changed:
            changed.append("queue")
    if not changed:
        return None, hashes
    body = json.dumps(
        {
            "topics": changed,
            "needs_you_count": open_needs_you_count(snapshot.get("needs_you", [])),
        },
        separators=(",", ":"),
    )
    return f"event: update\ndata: {body}\n\n".encode(), hashes


def _event_keepalive_due(last_keepalive: float, now: float) -> bool:
    return now - last_keepalive >= SSE_KEEPALIVE_INTERVAL


def _sse_file_poll_due(last_file_scan: float, now: float) -> bool:
    return last_file_scan == 0.0 or now - last_file_scan >= SSE_FILE_POLL_INTERVAL


def _sse_projection_due(
    files: tuple[tuple[str, int, int, int, int], ...],
    previous_files: tuple[tuple[str, int, int, int, int], ...] | None,
) -> bool:
    return previous_files is None or files != previous_files


def _sse_source_signature(
    files: tuple[tuple[Any, ...], ...],
    plan_reads: PlanReads | None,
    inbox_version: str | None,
) -> tuple[tuple[Any, ...], ...]:
    if plan_reads is not None and plan_reads.enabled:
        files = (*files, ("plan-generation", plan_reads.generation_value(), 0, 0, 0))
    if inbox_version is not None:
        files = (*files, ("inbox-version", inbox_version, 0, 0, 0))
    return files


def _invalidate_dashboard(dashboard: DashboardData) -> None:
    dashboard.read_cache.clear()
    dashboard.snapshot_loaded_at = 0


async def _sse_orchestrators(dashboard: DashboardData) -> dict[str, Any]:
    agents = await dashboard.agents()
    if dashboard.agents_refresh is not None:
        await dashboard.agents_refresh
        agents = dashboard.cached_agents
    plan_generation_changed = (
        dashboard.plan_reads is not None
        and dashboard.plan_reads.enabled
        and dashboard.snapshot_plan_generation
        != dashboard.plan_reads.generation_value()
    )
    snapshot_valid = (
        dashboard.snapshot_loaded_at > 0
        and agents == dashboard.snapshot.get("activity_agents", [])
        and not plan_generation_changed
    )
    if not snapshot_valid:
        dashboard.snapshot_loaded_at = 0
        snapshot = dict(await dashboard.orchestrators())
    else:
        snapshot = dashboard.snapshot
    return dashboard.include_needs_you(snapshot, await dashboard.request_needs_you())


def _dashboard_watched_roots(
    data_dir: Path,
    working_dir: Path | None,
    *,
    watch_plans: bool = True,
    watch_inbox: bool = True,
) -> tuple[Path, ...]:
    roots = [
        *workitem_store_files(data_dir),
        *decision_store_files(data_dir / "decisions"),
    ]
    if working_dir is not None:
        if watch_inbox:
            roots.append(working_dir / ".cache" / "inbox")
        if watch_plans:
            roots.append(working_dir / "plans")
    return tuple(roots)


def _closed_plan_ids(plans: Any) -> set[str]:
    if isinstance(plans, dict):
        plans = list(plans.values())
    if not isinstance(plans, list):
        return set()
    closed = set()
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        if (
            plan.get("status") in CONCLUDED_PLAN_STATUSES
            or plan.get("merge_state") == "merged"
        ) and plan.get("id"):
            closed.add(str(plan["id"]))
        closed.update(_closed_plan_ids(plan.get("children", [])))
    return closed


def _bound_addresses_for_closed_plans(
    plans: Any, bindings: list[dict[str, Any]]
) -> set[str]:
    """Map closed plan IDs to bound senders for open-mail filtering."""
    closed_ids = _closed_plan_ids(plans)
    return {
        str(binding["address"])
        for binding in bindings
        if binding.get("address") and binding.get("plan_id") in closed_ids
    }


def _needs_you_items(
    items: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    waiting_ids: set[str],
) -> list[dict[str, Any]]:
    """Project plan decisions from the shared waiting set; preserve other senders."""
    result = []
    for item in items:
        sender = item.get("sender")
        plan_id = (
            plan_id_for_address(sender, plans, bindings)
            if isinstance(sender, str)
            else None
        )
        bound_sender = any(
            isinstance(binding, dict) and binding.get("address") == sender
            for binding in bindings
        )
        if (plan_id is None and not bound_sender) or plan_id in waiting_ids:
            result.append(item)
    return result


async def _events_snapshot(
    dashboard: DashboardData,
    work_item_store: WorkItemStore,
    orchestrators: dict[str, Any],
) -> dict[str, Any]:
    items = await _projected_mailbox_items(dashboard)
    mailbox = _mailbox_payload(items)
    mailbox["open"] = await dashboard.open_mailbox_items(items)
    open_ids = {item["msg_id"] for item in mailbox["open"]}
    mailbox["all"] = [
        {**item, "mailbox_open": item["msg_id"] in open_ids} for item in mailbox["all"]
    ]
    public_orchestrators = _public_orchestrators(orchestrators)
    return {
        "items": items,
        "mailbox": mailbox,
        "permissions": mailbox["permissions"],
        "work_items": work_items_snapshot(work_item_store),
        **public_orchestrators,
    }


async def _retry_permission(key: str, dashboard: DashboardData) -> JSONResponse | None:
    decisions = dashboard.decisions
    entry = decisions.get_entry(key)
    if entry is None or not decisions.permission_entry(key):
        return None
    if entry.status not in {"failed", "stored"}:
        return JSONResponse({"entry_id": entry.entry_id, "status": entry.status})
    item = next(
        (
            row
            for row in await _projected_mailbox_items(dashboard)
            if row["msg_id"] == entry.decision_id
        ),
        None,
    )
    if item is None:
        return JSONResponse({"error": "permission request not found"}, status_code=404)
    try:
        response = await dashboard.respond(
            item["sender"],
            item.get("request_id", entry.decision_id),
            _permission_decision(entry.body, item.get("options", [])),
            item.get("harness"),
        )
        if response != "responded":
            _raise_permission_response_error(response)
    except Exception:  # noqa: BLE001 - retain failed state for another retry
        result = decisions.resolve_permission(entry.entry_id, False)
    else:
        result = decisions.resolve_permission(entry.entry_id, True)
    return JSONResponse({"entry_id": result.entry_id, "status": result.status})


async def _mailbox_list_json(request: Request) -> JSONResponse:
    dashboard: DashboardData = request.app.state.dashboard
    items = await _projected_mailbox_items(dashboard)
    try:
        limit = min(
            max(int(request.query_params.get("limit", MAILBOX_PAGE_SIZE)), 1),
            MAILBOX_MAX_PAGE_SIZE,
        )
    except ValueError:
        return JSONResponse({"error": "limit must be an integer"}, status_code=400)
    before = request.query_params.get("before") or None
    requested_ids = request.query_params.getlist("ids")
    if len(requested_ids) > MAILBOX_IDS_MAX:
        return JSONResponse({"error": "too many mailbox ids"}, status_code=400)
    try:
        mailbox = _mailbox_payload(
            items,
            limit=limit,
            before=before,
            ids=set(requested_ids) if requested_ids else None,
        )
    except ValueError:
        return JSONResponse({"error": "invalid mailbox cursor"}, status_code=400)
    mailbox["open"] = await dashboard.open_mailbox_items(items)
    open_ids = {item["msg_id"] for item in [*mailbox["open"], *mailbox["permissions"]]}
    if requested_ids:
        return JSONResponse(
            {"items": [_mailbox_summary(item, open_ids) for item in mailbox["all"]]}
        )
    mailbox["all"] = [
        {**item, "mailbox_open": item["msg_id"] in open_ids} for item in mailbox["all"]
    ]
    return JSONResponse(mailbox)


async def _mailbox_detail_json(request: Request) -> JSONResponse:
    dashboard: DashboardData = request.app.state.dashboard
    decision_id = request.path_params["decision_id"]
    item = next(
        (
            row
            for row in await _projected_mailbox_items(dashboard)
            if row["msg_id"] == decision_id
        ),
        None,
    )
    if item is None:
        return JSONResponse({"error": "decision not found"}, status_code=404)
    return JSONResponse(item)


def _answer_file_decision(
    dashboard: DashboardData,
    item: dict[str, Any],
    idempotency_key: str,
    body: str,
) -> tuple[int, dict[str, Any]]:
    notes_path = Path(str(item.get("notes", "")))
    with _FILE_DECISION_LOCK:
        try:
            value = json.loads(notes_path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            return 404, {"error": "decision file not found"}
        if not isinstance(value, dict):
            return 404, {"error": "decision file not found"}
        answered = value.get("answered")
        if isinstance(answered, dict):
            if answered.get("idempotency_key") != idempotency_key:
                return 409, {"error": "decision already answered"}
            return 200, {
                "entry_id": idempotency_key,
                "status": "sent",
                "notes_path": str(notes_path),
                "reply": answered.get("choice", ""),
            }
        if value.get("answer") or answered:
            return 409, {"error": "decision already answered"}
        try:
            dashboard.cli.send(
                sender="main",
                recipient=item["sender"],
                kind="info",
                text=f"Decision answered: {body}",
                notes=str(notes_path),
            )
        except (OSError, AttributeError, TypeError, ValueError, RuntimeError) as exc:
            return 502, {"error": str(exc)}
        value["answered"] = {
            "choice": body,
            "ts": datetime.now(UTC).isoformat(),
            "idempotency_key": idempotency_key,
        }
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=notes_path.parent,
                prefix=f".{notes_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, notes_path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            return 500, {"error": str(exc)}
    return 200, {
        "entry_id": idempotency_key,
        "status": "sent",
        "notes_path": str(notes_path),
        "reply": body,
    }


def _validated_mailbox_answer(
    item: dict[str, Any], option: str | None, free_text: str
) -> tuple[str | None, str | None]:
    if item["kind"] == "permission" and (option is None or free_text):
        return None, "permission answers must use an offered option"
    if option is not None and not any(
        option == _option_text(value)
        or (isinstance(value, dict) and option == value.get("id"))
        for value in item.get("options", [])
    ):
        return None, "option is not available"
    if item["kind"] != "permission" and item.get("type") == "approval":
        body = _approval_answer_body(option, free_text)
        if body is not None:
            return body, None
        error = (
            "ask-more requires text"
            if option == "ask-more" and not free_text.strip()
            else "option is not available"
        )
        return None, error
    return "\n".join(value for value in (option, free_text) if value), None


async def _mailbox_answer(request: Request) -> JSONResponse:
    dashboard: DashboardData = request.app.state.dashboard
    decision_id = request.path_params["decision_id"]
    try:
        payload = await request.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    option = payload.get("option")
    free_text = payload.get("text", "")
    key = payload.get("idempotency_key")
    if (
        (option is not None and not isinstance(option, str))
        or not isinstance(free_text, str)
        or not isinstance(key, str)
        or not key
        or (not option and not free_text)
    ):
        return JSONResponse(
            {"error": "option or text, and idempotency_key are required"},
            status_code=400,
        )
    item = next(
        (
            row
            for row in await _projected_mailbox_items(dashboard)
            if row["msg_id"] == decision_id
        ),
        None,
    )
    if item is None:
        return JSONResponse({"error": "decision not found"}, status_code=404)
    body, error = _validated_mailbox_answer(item, option, free_text)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    if body is None:
        return JSONResponse({"error": "answer is required"}, status_code=400)
    if item["msg_id"].startswith("file-"):
        status_code, result = await asyncio.to_thread(
            _answer_file_decision, dashboard, item, key, body
        )
        if status_code == 200:
            dashboard.read_cache.invalidate("mailbox", refresh=False)
            dashboard.read_cache.invalidate(
                f"plan-decision-files:{_dashboard_working_dir(dashboard.cli)}",
                refresh=False,
            )
        return JSONResponse(result, status_code=status_code)
    result = dashboard.decisions.submit_answer(decision_id, key, item["sender"], body)
    if item["sender"] == GOVERNOR and body.splitlines()[0] == "Resume":
        try:
            await request.app.state.bot_control.resume("user")
        except ControlError:
            logger.warning("governor Mailbox resume refused: bot is killed")
    if (
        item["kind"] == "permission"
        and result.entry_id
        and result.status in {"stored", "failed"}
    ):
        try:
            response = await dashboard.respond(
                item["sender"],
                item.get("request_id", decision_id),
                _permission_decision(option or "", item.get("options", [])),
                item.get("harness"),
            )
            if response != "responded":
                _raise_permission_response_error(response)
        except Exception:  # noqa: BLE001 - record sidecar failure for retry/inspection
            result = dashboard.decisions.resolve_permission(result.entry_id, False)
        else:
            result = dashboard.decisions.resolve_permission(result.entry_id, True)
    dashboard.projector.project()
    dashboard.read_cache.invalidate("mailbox", refresh=False)
    await _refresh_mailbox_after_action(dashboard, "answer")
    sent_reply = _stored_mailbox_reply(dashboard.decisions, decision_id)
    return JSONResponse(
        {
            "entry_id": result.entry_id,
            "status": result.status,
            "notes_path": result.notes_path,
            "reply": sent_reply.get("reply", body),
            "sent_at": sent_reply.get("sent_at"),
        },
        status_code=result.status_code,
    )


def _approval_answer_body(option: str | None, text: str) -> str | None:
    if option == "ask-more":
        return f"ASK-MORE: {text}" if text.strip() else None
    if option == "approve":
        return f"APPROVED: {text}" if text else "APPROVED"
    if option == "hold":
        return f"HOLD: {text}" if text else "HOLD"
    return None


async def _mailbox_evidence(request: Request) -> Response:
    dashboard: DashboardData = request.app.state.dashboard
    decision_id = request.path_params["decision_id"]
    try:
        index = int(request.path_params["index"])
    except ValueError:
        return JSONResponse({"error": "evidence not found"}, status_code=404)
    item = next(
        (
            row
            for row in await _projected_mailbox_items(dashboard)
            if row["msg_id"] == decision_id
        ),
        None,
    )
    evidence = item.get("evidence", []) if item else []
    if not isinstance(evidence, list) or not 0 <= index < len(evidence):
        return JSONResponse({"error": "evidence not found"}, status_code=404)
    attachment = evidence[index]
    path = attachment.get("path") if isinstance(attachment, dict) else None
    if not isinstance(path, str):
        return JSONResponse({"error": "evidence not found"}, status_code=404)
    resolved = resolve_evidence_path(path, dashboard.evidence_roots)
    if resolved is None:
        return JSONResponse({"error": "evidence not found"}, status_code=404)
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }[resolved.suffix.lower()]
    return Response(
        resolved.read_bytes(),
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _permission_decision(option: str, options: list[Any]) -> str:
    selected = next(
        (
            value
            for value in options
            if _option_text(value) == option
            or (isinstance(value, dict) and value.get("id") == option)
        ),
        None,
    )
    if selected is None:
        raise ValueError("permission option is unavailable")
    kind = (
        (selected.get("kind") or selected.get("id"))
        if isinstance(selected, dict)
        else selected
    )
    if kind not in {"allow", "deny"}:
        raise ValueError("permission option has no allow/deny kind")
    return str(kind)


async def _mailbox_dismiss(request: Request) -> JSONResponse:
    return await _mailbox_move(request, "dismiss")


async def _mailbox_restore(request: Request) -> JSONResponse:
    return await _mailbox_move(request, "restore")


async def _mailbox_move(request: Request, action: str) -> JSONResponse:
    """Dismiss or restore a message in the decision store; never acknowledges it."""
    dashboard: DashboardData = request.app.state.dashboard
    message_id = request.path_params["decision_id"]
    dashboard.projector.project()
    dashboard.inbox()
    move = getattr(dashboard.decisions, action)
    if not move(message_id):
        return JSONResponse(
            {"error": f"message not found to {action}"}, status_code=404
        )
    dashboard.projector.project()
    dashboard.read_cache.invalidate("mailbox", refresh=False)
    await _refresh_mailbox_after_action(dashboard, action)
    done = "dismissed" if action == "dismiss" else "restored"
    return JSONResponse({done: True, "msg_id": message_id})


async def _brand_asset(request: Request) -> Response:
    asset = request.url.path.lstrip("/")
    if asset == "favicon.ico":
        asset = "favicon-32.png"
    return FileResponse(UI_DIR / asset, headers={"Cache-Control": "no-cache"})


async def _settings_json(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            **read_settings(request.app.state.settings_path),
            "options": list(APP_ICON_OPTIONS),
        }
    )


async def _settings_update(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            _raise_invalid_settings_body()
        settings = write_settings(request.app.state.settings_path, body.get("app_icon"))
    except json.JSONDecodeError, UnicodeError, TypeError, ValueError:
        return JSONResponse({"error": "invalid app_icon"}, status_code=400)
    return JSONResponse(settings)


def _raise_permission_response_error(response: str) -> Never:
    raise RuntimeError(f"permission response {response}")


def _raise_invalid_settings_body() -> Never:
    raise TypeError("request body must be an object")


def _shell(name: str) -> Response:
    index = UI_DIR / name
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        "<!doctype html><title>Varde Runner UI not built</title>"
        "<h1>Dashboard UI not built</h1><p>Build it with "
        "<code>npm ci --prefix runner/ui &amp;&amp; "
        "npm run build --prefix runner/ui</code>.</p>",
        status_code=503,
    )


async def _ui_shell(request: Request) -> Response:
    return _shell("index.html")


async def _settings_section_shell(request: Request) -> Response:
    section = request.path_params["section"]
    return _shell(f"settings/{section}.html")


async def _plan_shell(request: Request) -> Response:
    return _shell("spa-fallback.html")


async def _chats_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/", status_code=307)


async def _home_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/", status_code=307)


async def _pins_json(request: Request) -> JSONResponse:
    return JSONResponse({"pins": read_pins(request.app.state.pins_path)})


async def _pins_update(request: Request) -> JSONResponse:
    body_bytes = await request.body()
    if len(body_bytes) > MAX_PINS_BODY_BYTES:
        return JSONResponse({"error": "invalid pins"}, status_code=413)
    try:
        body = json.loads(body_bytes)
    except json.JSONDecodeError, UnicodeError:
        return JSONResponse({"error": "invalid pins"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid pins"}, status_code=400)
    try:
        pins = write_pins(request.app.state.pins_path, body.get("pins"))
    except TypeError, ValueError:
        return JSONResponse({"error": "invalid pins"}, status_code=400)
    return JSONResponse({"pins": pins})


def _orchestrator_status_route(dashboard: DashboardData, cli: Any, data_dir: Path):
    async def ask_status(request: Request) -> JSONResponse:
        address = request.path_params["address"]
        snapshot = await dashboard.orchestrators()
        target = next(
            (row for row in snapshot.get("plans", []) if row.get("address") == address),
            None,
        )
        if target is None or not target.get("can_ask_status"):
            return JSONResponse(
                {"error": "orchestrator is not idle or stalled"}, status_code=404
            )
        sender = getattr(cli, "send", None)
        if not callable(sender):
            return JSONResponse(
                {"error": "message delivery is unavailable"}, status_code=502
            )
        try:
            notes_path = data_dir / f"status-request-{uuid.uuid4().hex}.json"
            notes_path.write_text("{}\n", encoding="utf-8")
            await asyncio.to_thread(
                sender,
                sender="main",
                recipient=address,
                kind="info",
                text="status?",
                notes=str(notes_path),
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return JSONResponse(
                {"error": f"status request failed: {type(exc).__name__}"},
                status_code=502,
            )
        return JSONResponse({"status": "sent", "address": address})

    return ask_status


def create_app(  # noqa: C901, PLR0913, PLR0915 - route wiring stays together
    *,
    data_dir: Path,
    cli: VardeCLI | Any | None = None,
    decisions: DecisionStore | None = None,
    bound_port: int | None = None,
    agents: Callable[[], Any] | None = None,
    allowed_hosts: frozenset[str] = frozenset(),
    user_credential: UserCredential | None = None,
    require_user_pairing: bool | None = None,
) -> Starlette:
    data_dir.mkdir(parents=True, exist_ok=True)
    pairing_enforced = (
        require_user_pairing
        if require_user_pairing is not None
        else user_credential is not None
    )
    resolved_cli: Any = cli if cli is not None else VardeCLI()

    def get_metrics_supervisor() -> Any:
        return get_supervisor()

    card_metrics = CardMetricsRecorder(get_metrics_supervisor)

    resolved_decisions = decisions or DecisionStore(
        data_dir / "decisions",
        send=resolved_cli.send,
        write_back=getattr(resolved_cli, "answer_plan_question", None),
        recorder=card_metrics,
    )
    working_dir = _dashboard_working_dir(resolved_cli)
    settings_path = (working_dir or data_dir) / ".cache" / "dashboard" / "settings.json"
    pins_path = (working_dir or data_dir) / ".cache" / "dashboard" / "pins.json"
    message_reader = getattr(resolved_cli, "read_messages", None)
    uses_cli_reader = (
        isinstance(resolved_cli, VardeCLI)
        and getattr(message_reader, "__func__", None) is VardeCLI.read_messages
    )
    if not uses_cli_reader:
        working_dir = None
    sweep_working_dir = working_dir or getattr(resolved_cli, "cwd", data_dir)
    sweep_state_path = (
        Path(sweep_working_dir) / ".cache" / "learn" / "runner-sweep.json"
    )
    soak_working_dir = Path(getattr(resolved_cli, "cwd", data_dir))
    soak_state_path = soak_working_dir / ".cache" / "mail-soak" / "runner-job.json"
    review_state_path = soak_working_dir / ".cache" / "learn" / "runner-review.json"

    async def execute_sweep() -> tuple[int, str, str]:
        environment = {**os.environ, **getattr(resolved_cli, "env", {})}
        environment["VARDE_WORKING_DIR"] = str(sweep_working_dir)
        process = await asyncio.create_subprocess_exec(
            "varde",
            "learn",
            "sweep",
            "--json",
            cwd=sweep_working_dir,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await process.communicate()
        except BaseException:
            process.kill()
            await process.wait()
            raise
        return (
            process.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    async def notify_sweep_failure(run_id: str, message: str) -> None:
        sender = getattr(resolved_cli, "send", None)
        if not callable(sender):
            return
        notes_dir = sweep_state_path.parent / "notifications"
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes_path = notes_dir / f"{sha256(run_id.encode()).hexdigest()}.json"
        notes_path.write_text(
            json.dumps(
                {
                    "title": "Daily learn sweep failed",
                    "run_id": run_id,
                    "failures": sweep_job.state.get("failures", []),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        await asyncio.to_thread(
            sender,
            sender="varde-runner",
            recipient="main",
            kind="info-failure",
            text=message,
            notes=str(notes_path),
        )

    sweep_job = SweepJob(
        sweep_state_path,
        execute=execute_sweep,
        notify=(
            notify_sweep_failure
            if callable(getattr(resolved_cli, "send", None))
            else None
        ),
        messages=getattr(resolved_cli, "read_messages", None),
        schedule_time=configured_schedule_time(
            os.environ.get("VARDE_LEARN_SWEEP_TIME", "03:00")
        ),
    )

    async def execute_soak() -> tuple[int, str, str]:
        environment = {**os.environ, **getattr(resolved_cli, "env", {})}
        environment["VARDE_WORKING_DIR"] = str(soak_working_dir)
        process = await asyncio.create_subprocess_exec(
            "varde",
            "msg",
            "soak",
            "--write",
            "--json",
            cwd=soak_working_dir,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await process.communicate()
        except BaseException:
            process.kill()
            await process.wait()
            raise
        return (
            process.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    async def notify_soak_failure(run_id: str, message: str) -> None:
        sender = getattr(resolved_cli, "send", None)
        if not callable(sender):
            return
        notes_dir = soak_state_path.parent / "notifications"
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes_path = notes_dir / f"{sha256(run_id.encode()).hexdigest()}.json"
        notes_path.write_text(
            json.dumps(
                {
                    "title": "Daily mail soak failed",
                    "run_id": run_id,
                    "error": soak_job.state.get("error"),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        await asyncio.to_thread(
            sender,
            sender="varde-runner",
            recipient="main",
            kind="info-failure",
            text=message,
            notes=str(notes_path),
        )

    soak_job = SoakJob(
        soak_state_path,
        execute=execute_soak,
        notify=(
            notify_soak_failure
            if callable(getattr(resolved_cli, "send", None))
            else None
        ),
        messages=getattr(resolved_cli, "read_messages", None),
        schedule_time=configured_soak_schedule_time(
            os.environ.get(MAIL_SOAK_SCHEDULE_ENV, "03:15")
        ),
    )
    job_connection = open_job_store(data_dir)

    async def execute_review() -> tuple[int, str, str]:
        budget = get_budget(job_connection, JOBS_BY_KEY["review"])
        if budget is None:
            raise RuntimeError("review job has no configured token budget")
        environment = {**os.environ, **getattr(resolved_cli, "env", {})}
        environment["VARDE_WORKING_DIR"] = str(sweep_working_dir)
        return await execute_review_cli(
            budget_tokens=budget,
            cwd=sweep_working_dir,
            environment=environment,
            timeout_seconds=configured_review_timeout_seconds(
                os.environ.get("VARDE_LEARN_REVIEW_TIMEOUT_SECONDS")
            ),
        )

    review_job = ReviewJob(
        review_state_path,
        execute=execute_review,
        schedule_time=configured_review_schedule_time(
            os.environ.get("VARDE_LEARN_REVIEW_TIME", "04:00")
        ),
    )
    jobs_controller = JobsController(
        job_connection, {"sweep": sweep_job, "soak": soak_job, "review": review_job}
    )
    for job_key, job in jobs_controller.jobs.items():
        spec = JOBS_BY_KEY[job_key]
        job.enabled_check = lambda spec=spec: jobs_controller.enabled(spec)
        job.run_started = lambda trigger, key=job_key: jobs_controller.start(
            key, trigger
        )
        job.run_finished = lambda run_id, snapshot, error, key=job_key: (
            jobs_controller.finish(key, run_id, snapshot, error)
        )
    inbox_cache = InboxStoreCache(working_dir) if working_dir is not None else None
    dashboard_ref: dict[str, DashboardData] = {}

    projector = InboxProjector(
        data_dir / "inbox.sqlite3",
        read_messages=(
            inbox_cache.read_messages if inbox_cache is not None else message_reader
        ),
        messages_repository=(
            inbox_cache.repository
            if inbox_cache is not None
            else getattr(resolved_cli, "_messages", None)
            if uses_cli_reader
            else None
        ),
        read_plan=_projector_plan_reader(resolved_cli, dashboard_ref),
        decision_store=resolved_decisions,
    )
    plan_reads = (
        PlanReads(
            working_dir,
            Path(getattr(resolved_cli, "cwd", working_dir)),
            getattr(resolved_cli, "env", None),
        )
        if working_dir is not None
        else None
    )
    watched_roots = _dashboard_watched_roots(
        data_dir,
        working_dir,
        watch_plans=plan_reads is None or not plan_reads.enabled,
        watch_inbox=inbox_cache is None,
    )
    dashboard = DashboardData(
        resolved_cli,
        projector,
        resolved_decisions,
        agents,
        getattr(resolved_cli, "models", None),
        inbox_cache=inbox_cache,
        watched_roots=watched_roots,
        evidence_roots=((working_dir / "plans",) if working_dir is not None else ()),
        plan_reads=plan_reads,
        queue_working_dir=working_dir,
    )
    resolved_cli.plan_reads = dashboard.plan_reads
    dashboard_ref["dashboard"] = dashboard
    work_item_store = WorkItemStore(data_dir)

    async def orchestrators_json(request: Request) -> JSONResponse:
        snapshot = dashboard.include_needs_you(
            dict(await dashboard.orchestrators()), await dashboard.request_needs_you()
        )
        return JSONResponse(_public_orchestrators(snapshot))

    async def needs_you_count_json(request: Request) -> JSONResponse:
        count = open_needs_you_count(await dashboard.needs_you_threads())
        return JSONResponse({"needs_you_count": count})

    status_route = _orchestrator_status_route(dashboard, resolved_cli, data_dir)

    async def role_models_json(request: Request) -> JSONResponse:
        return JSONResponse(await dashboard.role_models())

    async def sweep_status(request: Request) -> JSONResponse:
        return JSONResponse(request.app.state.sweep_job.snapshot())

    async def sweep_run_now(request: Request) -> JSONResponse:
        return JSONResponse(await request.app.state.sweep_job.run_now())

    async def mail_soak_report(request: Request) -> JSONResponse:
        reports = soak_working_dir / "metrics" / "mail-soak"
        report = await asyncio.to_thread(_latest_mail_soak_report, reports)
        if report is None:
            return JSONResponse(
                {"error": "mail soak report not found"}, status_code=404
            )
        return JSONResponse(report)

    async def agent_capabilities_json(request: Request) -> JSONResponse:
        registry = getattr(request.app.state, "registry", None) or dashboard.registry
        if registry is None:
            return JSONResponse({})
        return JSONResponse(agent_capabilities(registry))

    async def retry(request: Request) -> JSONResponse:
        key = request.path_params["key"]
        permission_result = await _retry_permission(key, dashboard)
        if permission_result is not None:
            return permission_result
        try:
            result = resolved_decisions.retry(key)
        except KeyError:
            return JSONResponse({"error": "entry not found"}, status_code=404)
        return JSONResponse({"entry_id": result.entry_id, "status": result.status})

    async def events(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[bytes]:
            previous_hashes = None
            previous_files = None
            last_full_refresh = 0.0
            last_file_scan = 0.0
            last_keepalive = time.monotonic()
            while True:
                now = time.monotonic()
                files = previous_files or ()
                if _sse_file_poll_due(last_file_scan, now):
                    files = await asyncio.to_thread(
                        watched_files_signature, dashboard.watched_roots
                    )
                    inbox_version = (
                        dashboard.inbox_cache.repository.version().value
                        if dashboard.inbox_cache is not None
                        else None
                    )
                    files = _sse_source_signature(
                        files, dashboard.plan_reads, inbox_version
                    )
                    last_file_scan = time.monotonic()
                if files != previous_files:
                    _invalidate_dashboard(dashboard)
                if _sse_refresh_due(files, previous_files, last_full_refresh, now):
                    if _sse_projection_due(files, previous_files):
                        await asyncio.to_thread(projector.project)
                    current = await _events_snapshot(
                        dashboard, work_item_store, await _sse_orchestrators(dashboard)
                    )
                    frame, previous_hashes = _event_update_frame(
                        current, previous_hashes
                    )
                    if frame is not None:
                        yield frame
                    previous_files = files
                    last_full_refresh = now
                now = time.monotonic()
                if _event_keepalive_due(last_keepalive, now):
                    yield b": keepalive\n\n"
                    last_keepalive = now
                await asyncio.sleep(2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    takeover_manager: Takeover | None = None
    bot_data = open_data(working_dir or data_dir, load_data_config())
    bot_tokens = BotTokens()
    bot_audit = BotAudit(bot_data.bot, bot_data.chat)

    def bot_permission_sink(session_id: str, decision: Any, tool: str) -> None:
        """Audit a bot permission decision; it counts toward loop detection."""
        try:
            row = bot_audit.record(
                "call",
                action="permission",
                route=f"permission {tool}",
                args={"tool": tool, "action": decision.action},
                actor=BOT_ACTOR,
                status="allowed" if decision.allow else "denied",
                reason=decision.reason,
                agent_id=session_id,
            )
            if not decision.allow:
                bot_audit.post_event(row)
        except Exception:
            logger.exception("could not audit a bot permission decision")

    async def raise_governor_mailbox(reason: str) -> None:
        """Ask the user, in the Mailbox, whether to resume a governor pause."""
        notes_dir = data_dir / "governor-notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes = notes_dir / f"pause-{uuid.uuid4().hex}.json"
        notes.write_text(
            json.dumps(
                {
                    "type": "question",
                    "asked": f"The bot was paused: {reason}. Resume it?",
                    "why": "The governor paused the manager bot; only you can resume.",
                    "options": ["Resume", "Keep paused"],
                }
            ),
            encoding="utf-8",
        )
        await asyncio.to_thread(
            resolved_cli.send,
            sender=GOVERNOR,
            recipient="main",
            kind="needs-user",
            text=f"Bot paused: {reason}",
            notes=str(notes),
        )

    merge_approvals = MergeApprovals(working_dir or data_dir)
    merge_secret_path = (
        user_credential.path.with_name("merge-approver-main")
        if user_credential is not None
        else data_dir / "merge-approver-main"
    )
    merge_approver_secret = MergeApproverSecret(merge_secret_path)
    merge_approver_secret.start()
    bot_control = BotControl(
        repo=bot_data.bot,
        tokens=bot_tokens,
        audit=bot_audit,
        supervisor=lambda: get_supervisor(),  # noqa: PLW0108 - bound later in create_app
        caps=lambda: load_caps(config_path()),
        raise_mailbox=raise_governor_mailbox,
    )

    def supervisor_started(value: Supervisor) -> None:
        value.takeover = takeover_manager
        value.bot_permission_sink = bot_permission_sink
        value.bot_token_issuer = bot_tokens.overlay
        value.bot_descendant_issuer = bot_tokens.descendant_overlay
        value.bot_token_revoker = bot_tokens.revoke_session
        bot_audit.start_retries()
        app.state.supervisor = value
        if takeover_manager is not None:
            asyncio.create_task(takeover_manager.start(value))

    manager_wake_ref: dict[str, Any] = {}

    async def deliver_manager_wake(action: dict[str, Any]) -> tuple[str, str]:
        wake = manager_wake_ref.get("handler")
        if wake is None:
            return "failed", "no-send"
        return await wake(action)

    (
        start_work_item,
        base_lifespan,
        get_registry,
        get_supervisor,
    ) = _work_item_lifecycle(
        data_dir,
        supervisor_started,
        plan_watch=(
            dashboard.plan_reads.watch
            if dashboard.plan_reads is not None and dashboard.plan_reads.enabled
            else None
        ),
        manager_wake=deliver_manager_wake,
    )
    queue_plan_sources = None
    if dashboard.plan_reads is not None and dashboard.plan_reads.enabled:
        plan_reads = dashboard.plan_reads
        queue_plan_sources = PlanReadSources(
            queue_inputs=dashboard.queue_inputs,
            generation=plan_reads.generation_value,
            detail=plan_reads.detail_records,
            records=plan_reads.list_records,
            persisted=lambda: plan_reads.has_persisted_index,
            ready=lambda: plan_reads.ready,
        )
    queue_routes = create_queue_routes(
        resolved_cli,
        working_dir or data_dir,
        activity_reader=dashboard.orchestrators,
        activity_signature=lambda: dashboard.snapshot_loaded_at,
        plan_read_sources=queue_plan_sources,
    )
    approve_page_routes = create_approve_page_routes(dashboard.plan_status)
    task_queue_routes = create_task_queue_routes(
        working_dir or data_dir, get_supervisor
    )
    queue_route = next(route for route in queue_routes if route.path == "/api/queue")
    queue_prewarm = getattr(queue_route.endpoint, "prewarm", None)
    dashboard.registry = get_registry()
    planner_config_path = config_path()
    try:
        planner_role_config = load_config(
            planner_config_path, dashboard.registry.known_harnesses()
        )
    except ConfigError as exc:
        dashboard.planner_role_status = "invalid"
        dashboard.planner_role_error = str(exc)
        logger.warning(
            "Planner role is unavailable in %s: %s", planner_config_path, exc
        )
    else:
        try:
            planner_role_config.resolve("planner")
        except ConfigError as exc:
            dashboard.planner_role_status = "missing"
            dashboard.planner_role_error = str(exc)
            logger.warning(
                "Planner role is unavailable in %s: %s", planner_config_path, exc
            )
    dashboard.supervisor_getter = get_supervisor
    lifespan = _dashboard_lifespan(
        base_lifespan,
        dashboard,
        get_registry,
        get_supervisor,
        queue_prewarm,
    )

    chat_data = open_data(working_dir or data_dir, load_data_config())
    chat_repository = chat_data.chat
    takeover_manager = Takeover(chat_repository)

    def fail_manager_launch_race() -> Never:
        raise RuntimeError("manager bot launch raced with pause or kill")

    async def launch_manager(prompt: str) -> str:
        policy = policy_for("POST", "/api/agents")
        if policy is None or policy.kind != Kind.ALLOW or policy.constraint != "launch":
            raise RuntimeError("manager launch is not classified by the bot gateway")
        classified = Classified("POST /api/agents", policy, {})
        args = {
            "role": "manager-bot",
            "workspace": str(working_dir or data_dir),
            "address": {"slot": "manager"},
        }
        identity = BotIdentity(BOT_ACTOR, "manager-lifecycle")
        refusal = await bot_control.governor(identity, classified, args)
        if refusal is not None:
            row = bot_audit.record(
                "call",
                action="launch",
                route=classified.route_key,
                args=args,
                actor=identity.actor,
                status="denied",
                reason=refusal.reason,
            )
            bot_audit.post_event(row)
            raise RuntimeError(refusal.reason)
        try:
            call = bot_audit.record(
                "call",
                action="launch",
                route=classified.route_key,
                args=args,
                actor=identity.actor,
                status="allowed",
            )
            bot_audit.post_event(call)
            ref = await launch_agent(
                await get_supervisor(),
                None,
                args["workspace"],
                "manager-bot",
                prompt,
                {"slot": "manager"},
            )
            if bot_control.run_state() != "running":
                await (await get_supervisor()).stop(ref.session_id, GOVERNOR)
                fail_manager_launch_race()
        except Exception as exc:
            result = bot_audit.record(
                "result",
                action="launch",
                route=classified.route_key,
                args=args,
                actor=identity.actor,
                status="failed",
                reason=str(exc),
            )
            bot_audit.post_event(result)
            raise
        else:
            result = bot_audit.record(
                "result",
                action="launch",
                route=classified.route_key,
                args={**args, "agent_id": ref.session_id},
                actor=identity.actor,
                status="started",
                agent_id=ref.session_id,
            )
            bot_audit.post_event(result)
            return ref.session_id
        finally:
            bot_control.release(classified)

    async def commit_manager_notes(path: Path) -> None:
        root = Path.home() / "source" / "agent-memory"
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise RuntimeError("manager notes are outside agent-memory") from exc
        branch = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(root), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        )
        if branch.stdout.strip() != "main":
            raise RuntimeError(
                "manager notes can only be committed on agent-memory main"
            )
        await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(root), "add", "--", str(relative)],
            check=True,
        )
        await asyncio.to_thread(
            subprocess.run,
            [
                "git",
                "-C",
                str(root),
                "commit",
                "--only",
                "-m",
                "manager-bot: save lifecycle handoff",
                "--",
                str(relative),
            ],
            check=True,
        )

    manager_lifecycle = ManagerBotLifecycle(
        chat=chat_repository,
        working_dir=working_dir or data_dir,
        hooks=LifecycleHooks(
            get_supervisor=get_supervisor,
            launch=launch_manager,
            run_state=bot_control.run_state,
            commit_notes=commit_manager_notes,
        ),
    )
    manager_wake_ref["handler"] = ManagerBotWake(
        get_supervisor, paused=lambda: bot_control.run_state() != "running"
    )

    retry_manager_start_at = 0.0
    manager_role_signature: tuple[str, int, int] | None = None
    manager_role_enabled = False
    manager_role_present = False

    async def ensure_manager_bot() -> None:
        nonlocal retry_manager_start_at, manager_role_signature
        nonlocal manager_role_enabled, manager_role_present
        path = config_path()
        try:
            stat = path.stat()
            signature = (str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = (str(path), 0, 0)
        if signature != manager_role_signature:
            manager_role_signature = signature
            try:
                role_config = load_config(path, get_registry().known_harnesses())
                manager_role_present = "manager-bot" in role_config.roles
                role = role_config.resolve("manager-bot")
            except ConfigError as exc:
                manager_role_enabled = False
                manager_role_present = False
                if str(exc) == "unknown role: manager-bot":
                    logger.info("manager bot is disabled: manager-bot role is absent")
                else:
                    logger.exception("manager bot role could not be loaded")
                return
            manager_role_enabled = role.enabled
            if not manager_role_present:
                logger.info("manager bot is disabled: manager-bot role is absent")
        if not manager_role_enabled:
            return
        if time.monotonic() < retry_manager_start_at:
            return
        try:
            await manager_lifecycle.start()
        except Exception:
            retry_manager_start_at = time.monotonic() + 30
            logger.exception("manager bot could not be started")

    chat_delivery = ChatDelivery(
        chat_repository,
        get_supervisor,
        bot_paused=lambda: bot_control.run_state() != "running",
        ensure_bot=ensure_manager_bot,
    )
    chat_routes = create_chat_routes(chat_repository, chat_delivery)
    bot_action_routes = create_bot_action_routes(
        chat=chat_repository,
        cli=resolved_cli,
        working_dir=working_dir or data_dir,
        data_dir=data_dir,
    )
    instance_threads = InstanceThreads(
        chat_repository,
        plan_ids_from_working_dir(str(working_dir or data_dir)),
        messages=lambda: chat_data.messages,
    )
    instance_thread_routes = create_instance_threads_routes(
        instance_threads, get_supervisor
    )

    @asynccontextmanager
    async def runner_lifespan(app: Starlette) -> AsyncIterator[None]:
        card_metrics.bind_loop()

        def live_agent_rows() -> list[dict[str, Any]]:
            supervisor = getattr(app.state, "supervisor", None)
            return supervisor.store.sessions() if supervisor is not None else []

        async with lifespan(app):
            await asyncio.to_thread(resolved_decisions.recover_sending)
            await ensure_manager_bot()
            await chat_delivery.start()
            manager_task = (
                asyncio.create_task(manager_lifecycle.run())
                if manager_role_present
                else None
            )
            instance_thread_task = asyncio.create_task(
                instance_threads.run(lambda: getattr(app.state, "supervisor", None))
            )
            fail_stale_runs(job_connection)
            sweep_task = asyncio.create_task(sweep_job.run())
            soak_task = asyncio.create_task(soak_job.run())
            lease_expiry_task = asyncio.create_task(
                run_expiry_ticks(lambda: bot_data.queue)
            )
            snapshot_task = asyncio.create_task(
                run_snapshot_ticks(
                    snapshot_path(working_dir or data_dir), live_agent_rows
                )
            )
            try:
                yield
            finally:
                await chat_delivery.close()
                manager_lifecycle.stop()
                if manager_task is not None:
                    manager_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await manager_task
                instance_thread_task.cancel()
                with suppress(asyncio.CancelledError):
                    await instance_thread_task
                sweep_task.cancel()
                soak_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sweep_task
                with suppress(asyncio.CancelledError):
                    await soak_task
                if lease_expiry_task is not None:
                    lease_expiry_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await lease_expiry_task
                snapshot_task.cancel()
                with suppress(asyncio.CancelledError):
                    await snapshot_task
                job_connection.close()

    async def relay_json(request: Request) -> JSONResponse:
        if not getattr(request.app.state, "relay_enabled", False):
            return JSONResponse({"enabled": False})
        worker = getattr(request.app.state, "relay_worker", None)
        if worker is None:
            return JSONResponse({"enabled": False})
        snapshot = worker.snapshot()
        return JSONResponse({**snapshot, "enabled": True})

    async def get_runner_store():
        return (await get_supervisor()).store

    workspace_repos = configured_workspace_repos(
        config_path().read_text(encoding="utf-8") if config_path().exists() else ""
    )
    workspaces_service: WorkspacesService | None = (
        WorkspacesService(
            workspace_repos, env=child_environment(), get_store=get_runner_store
        )
        if workspace_repos
        else None
    )
    app = Starlette(
        lifespan=runner_lifespan,
        routes=[
            Route("/", _ui_shell),
            Route("/mailbox", _home_redirect),
            Route("/jobs", _ui_shell),
            Route("/roles", _ui_shell),
            Route("/new-item", _ui_shell),
            Route("/settings", _ui_shell),
            Route("/settings/{section:str}", _settings_section_shell),
            Route("/home", _home_redirect),
            Route("/queue", _ui_shell),
            Route("/queue/{role:str}", _plan_shell),
            Route("/plans", _ui_shell),
            Route("/agents", _ui_shell),
            Route("/chat", _ui_shell),
            Route("/chat/needs", _plan_shell),
            Route("/chats", _chats_redirect),
            Route("/agents/profile/{identity_id:str}", _plan_shell),
            Route("/plans/{plan_id:str}", _plan_shell),
            Route("/threads", _chats_redirect),
            Route("/threads/{thread_id:str}", _plan_shell),
            Route("/thread/{agent_id:str}", _plan_shell),
            Route("/profile/{agent_id:str}", _plan_shell),
            Route("/api/orchestrators", orchestrators_json),
            Route("/api/needs-you-count", needs_you_count_json),
            Route(
                "/api/orchestrators/{address:str}/status",
                status_route,
                methods=["POST"],
            ),
            Route("/api/relay", relay_json),
            Route("/api/probe", probe_route, methods=["POST"]),
            Route("/api/learn/sweep", sweep_status),
            Route("/api/learn/sweep/run", sweep_run_now, methods=["POST"]),
            Route("/api/mail-soak", mail_soak_report),
            *create_jobs_routes(jobs_controller),
            *create_runner_status_routes(get_registry, data_dir),
            *create_runner_config_routes(get_registry),
            *create_sdk_flip_routes(get_registry),
            create_runner_config_toml_view_route(),
            Route("/api/decision-metrics", decision_metrics),
            Route("/api/settings", _settings_json),
            Route("/api/settings", _settings_update, methods=["POST"]),
            Route("/api/pins", _pins_json),
            Route("/api/pins", _pins_update, methods=["PUT"]),
            Route("/api/roles/models", role_models_json),
            Route("/api/agents/capabilities", agent_capabilities_json),
            create_agent_watch_route(get_supervisor),
            *create_agents_routes(
                get_supervisor,
                on_identity_fallback=lambda agent_id: chat_repository.append_event(
                    "event",
                    "no match, used closest role",
                    f"/agents/{agent_id}",
                    "main",
                ),
            ),
            *bot_action_routes,
            *create_bot_audit_routes(bot_audit),
            *create_bot_routes(bot_control),
            *create_approval_routes(
                merge_approvals, merge_approver_secret, working_dir
            ),
            *approve_page_routes,
            *(
                create_pairing_routes(
                    user_credential, require_user_pairing=pairing_enforced
                )
                if user_credential
                else []
            ),
            *create_identities_routes(get_supervisor),
            *instance_thread_routes,
            *create_takeover_routes(takeover_manager, get_supervisor),
            *chat_routes,
            Route("/api/mailbox", _mailbox_list_json),
            Route("/api/mailbox/{decision_id:str}", _mailbox_detail_json),
            Route(
                "/api/mailbox/{decision_id:str}/evidence/{index:str}",
                _mailbox_evidence,
            ),
            Route(
                "/api/mailbox/{decision_id:str}/answer",
                _mailbox_answer,
                methods=["POST"],
            ),
            Route(
                "/api/mailbox/{decision_id:str}/dismiss",
                _mailbox_dismiss,
                methods=["POST"],
            ),
            Route(
                "/api/mailbox/{decision_id:str}/restore",
                _mailbox_restore,
                methods=["POST"],
            ),
            Route(
                "/mailbox/{decision_id:str}/answer", _mailbox_answer, methods=["POST"]
            ),
            Route("/entries/{key:str}/retry", retry, methods=["POST"]),
            Route("/events", events),
            Route("/favicon.svg", _brand_asset, name="favicon-svg"),
            Route("/favicon-16.png", _brand_asset, name="favicon-16"),
            Route("/favicon-32.png", _brand_asset, name="favicon-32"),
            Route("/favicon.ico", _brand_asset, name="favicon-ico"),
            Route("/apple-touch-icon.png", _brand_asset, name="apple-touch-icon"),
            Route("/manifest.webmanifest", _brand_asset, name="web-manifest"),
            Route("/icon-192.png", _brand_asset, name="icon-192"),
            Route("/icon-512.png", _brand_asset, name="icon-512"),
            Route("/icons/dark/{asset:str}", _brand_asset, name="dark-icon"),
            *create_newitem_routes(
                data_dir,
                work_item_store,
                get_registry,
                workspaces_service,
            ),
            *create_threads_routes(working_dir or data_dir),
            *queue_routes,
            *task_queue_routes,
            *create_role_queue_routes(dashboard, get_supervisor),
            create_role_queues_route(working_dir or data_dir),
            *guard_routes(),
            create_roles_route(registry_getter=get_registry),
            Mount(
                "/_app",
                app=StaticFiles(directory=str(UI_DIR / "_app"), check_dir=False),
                name="ui-assets",
            ),
            Mount(
                "/static",
                app=StaticFiles(directory=str(Path(__file__).parent / "static")),
                name="static",
            ),
        ],
    )
    app.state.cli = resolved_cli
    app.state.registry = get_registry()
    app.state.decisions = resolved_decisions
    app.state.projector = projector
    app.state.dashboard = dashboard
    app.state.sweep_job = sweep_job
    app.state.soak_job = soak_job
    app.state.bound_port = bound_port
    app.state.settings_path = settings_path
    app.state.pins_path = pins_path
    app.state.work_item_start = start_work_item
    app.state.bot_tokens = bot_tokens
    app.state.bot_audit = bot_audit
    app.state.bot_control = bot_control
    app.state.manager_lifecycle = manager_lifecycle

    async def bot_constraint_context() -> ConstraintContext:
        supervisor = await get_supervisor()
        addresses = bot_data.addresses
        plans_root = working_dir or data_dir

        def launched_by(agent_id: str) -> str | None:
            row = supervisor.resolve_session(agent_id)
            return row.get("launched_by") if row else None

        def plan_status(plan_id: str) -> str | None:
            record = _plan_record(plans_root, plan_id)
            return record.status if record is not None else None

        return ConstraintContext(
            workspace_listed=lambda workspace: (
                supervisor.store.get_workspace(workspace) is not None
            ),
            slot_bound=lambda slot: any(
                item.slot == slot and item.current_address for item in addresses.slots()
            ),
            plan_bound=lambda plan: any(
                plan in item.aliases and item.current_address
                for item in addresses.slots()
            ),
            launched_by=launched_by,
            plan_exists=lambda plan: _plan_record(plans_root, plan) is not None,
            plan_status=plan_status,
        )

    async def bot_race_hook(
        identity: BotIdentity, classified: Any, status: int, body: bytes
    ) -> None:
        """A launch finished after Pause or Kill: stop the agent it created."""
        try:
            agent_id = json.loads(body).get("agent_id")
        except ValueError, AttributeError:
            return
        if isinstance(agent_id, str):
            await (await get_supervisor()).stop(agent_id, "system:governor")

    if user_credential is not None:
        app.add_middleware(
            UserCredentialGate,
            credential=user_credential,
            routes=lambda: app.routes,
            require_user_pairing=pairing_enforced,
        )
    app.add_middleware(
        BotGateway,
        routes=lambda: app.routes,
        tokens=bot_tokens,
        audit=bot_audit,
        config=lambda: load_bot_config(config_path()),
        context=bot_constraint_context,
        run_state=bot_control.run_state,
        governor=bot_control.governor,
        after=bot_race_hook,
        release=bot_control.release,
    )
    app.add_middleware(
        LocalRequestGuard, bound_port=bound_port, allowed_hosts=allowed_hosts
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RequestTimingMiddleware)

    return app
