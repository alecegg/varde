"""Queue and plan comment HTTP routes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.comments import append_event, read_comments
from varde_runner.plans_repository import shared_plans_repository
from varde_runner.queue import (
    CATEGORY_LIMITS,
    UNCATEGORIZED,
    category_for_plan,
    flatten_plans,
    has_saved_order,
    move_order,
    next_up,
    parse_frontmatter,
    read_order,
    slot_usage,
    task_acceptance,
)
from varde_runner.wake import wake_agent_id
from varde_runner.web.activity import plan_activity, plan_id_for_address

logger = logging.getLogger(__name__)

QUEUE_CACHE_TTL = 3


@dataclass(frozen=True)
class PlanReadSources:
    queue_inputs: Callable[[], tuple[dict[str, Any], list[dict[str, Any]]]] | None = (
        None
    )
    generation: Callable[[], int] | None = None
    detail: Callable[[str], tuple[Any, tuple[Any, ...]] | None] | None = None
    records: Callable[[], tuple[Any, ...]] | None = None
    persisted: Callable[[], bool] | None = None
    ready: Callable[[], bool] | None = None


def _empty_queue_snapshot() -> dict[str, Any]:
    categories = {
        **{category: [] for category in CATEGORY_LIMITS},
        UNCATEGORIZED: [],
    }
    return {
        "categories": [
            {
                "id": category,
                "limit": CATEGORY_LIMITS.get(category, 0),
                "used": 0,
                "waiting": [],
                "next_up": None,
                "priority_set": False,
            }
            for category in categories
        ],
        "hidden": [],
        "slots": {"used": 0, "limit": sum(CATEGORY_LIMITS.values())},
    }


def create_queue_routes(  # noqa: C901, PLR0915 - route handlers and snapshot cache stay together
    cli: Any,
    working_dir: Path,
    activity_reader: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    *,
    activity_signature: Callable[[], object] | None = None,
    plan_read_sources: PlanReadSources | None = None,
) -> list[Route]:
    sources = plan_read_sources or PlanReadSources()
    previous_signature: str | None = None
    snapshot_loaded_at = 0.0
    snapshot_value: tuple[dict[str, Any], dict[str, Path]] | None = None
    snapshot_failure: Exception | None = None
    snapshot_failed_at = 0.0
    snapshot_refresh: asyncio.Task[tuple[dict[str, Any], dict[str, Path]]] | None = None
    snapshot_epoch = 0

    def snapshot_signature() -> str:
        nonlocal previous_signature, snapshot_loaded_at, snapshot_epoch
        plan_mtime = (
            sources.generation()
            if sources.generation is not None
            else max(
                (
                    path.stat().st_mtime_ns
                    for path in (working_dir / "plans").rglob("plan.md")
                ),
                default=0,
            )
        )
        order_path = working_dir / "queue-order.json"
        order_mtime = order_path.stat().st_mtime_ns if order_path.exists() else 0
        activity_key = activity_signature() if activity_signature else None
        signature = f"{plan_mtime}:{order_mtime}:{activity_key!r}"
        if previous_signature is not None and previous_signature != signature:
            snapshot_epoch += 1
            snapshot_loaded_at = 0.0
        previous_signature = signature
        return signature

    def build_snapshot(
        activity: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        statuses, bindings = (
            sources.queue_inputs()
            if sources.queue_inputs
            else (_plan_status(cli), _bindings(cli))
        )
        statuses = statuses if isinstance(statuses, dict) else {}
        status_plans = flatten_plans(statuses.get("plans", []))
        plans, plan_files, frontmatter, open_counts = _plan_metadata(
            working_dir,
            status_plans,
            getattr(cli, "env", None),
            sources.records() if sources.records is not None else None,
        )
        active_plans = activity.get("plans", []) if isinstance(activity, dict) else []
        agents = (
            activity.get("activity_agents", []) if isinstance(activity, dict) else []
        )
        active_by_id = {
            str(row.get("id")): row for row in active_plans if isinstance(row, dict)
        }
        orchestrator_titles = _queue_orchestrator_titles(
            plans, active_by_id, bindings, agents
        )
        categories = _categories(plans, frontmatter, orchestrator_titles)
        ordered = has_saved_order(working_dir / "queue-order.json")
        order = read_order(working_dir / "queue-order.json", categories)
        rows_by_id = {str(row.get("id")): row for row in plans if row.get("id")}
        valid_ids = {plan_id for ids in categories.values() for plan_id in ids}
        eligible = [row for row in plans if str(row.get("id", "")) in valid_ids]
        activity_by_id = {
            str(row["id"]): _plan_activity_for_queue(row, active_by_id, agents)
            for row in eligible
            if row.get("id")
        }
        running_ids = {
            plan_id
            for plan_id, status in activity_by_id.items()
            if status in {"running", "waiting", "idle", "stalled", "blocked"}
            and _is_live_orchestrator(active_by_id.get(plan_id, {}).get("agent_status"))
        }
        result = []
        for category in categories:
            waiting_ids = [
                item
                for item in order[category]
                if _is_waiting_plan(
                    item, rows_by_id, plan_files, frontmatter, activity_by_id
                )
            ]
            waiting = [rows_by_id[item] for item in waiting_ids]
            waiting_rows = [
                {
                    "id": str(row["id"]),
                    "title": row.get("title") or str(row["id"]),
                    "label": row.get("label") or row.get("title") or str(row["id"]),
                    "purpose": row.get("purpose", ""),
                    "group_name": row.get("group_name", ""),
                    "status": row.get("status", "unknown"),
                    "open_comments": open_counts.get(str(row["id"]), 0),
                    **_readiness(
                        plan_files[str(row["id"])],
                        open_counts.get(str(row["id"]), 0),
                        frontmatter.get(str(row["id"]), {}),
                    ),
                }
                for row in waiting
            ]
            usage = slot_usage(
                sorted(running_ids),
                set(categories[category]),
                CATEGORY_LIMITS.get(category, 0),
            )
            result.append(
                {
                    "id": category,
                    "limit": CATEGORY_LIMITS.get(category, 0),
                    "used": usage["used"],
                    "waiting": waiting_rows,
                    "next_up": next_up([row["id"] for row in waiting_rows])
                    if ordered
                    else None,
                    "priority_set": ordered,
                }
            )
        return (
            {
                "categories": result,
                "hidden": _hidden_plans(
                    plans,
                    frontmatter,
                    activity_by_id,
                ),
                "slots": slot_usage(
                    sorted(running_ids),
                    {
                        plan_id
                        for plan_ids in categories.values()
                        for plan_id in plan_ids
                    },
                    sum(CATEGORY_LIMITS.values()),
                ),
            },
            plan_files,
        )

    async def load_snapshot() -> tuple[dict[str, Any], dict[str, Path]]:
        activity: dict[str, Any] = {}
        if activity_reader is not None:
            value = await activity_reader()
            activity = value if isinstance(value, dict) else {}
        return await asyncio.to_thread(build_snapshot, activity)

    async def refresh_snapshot(
        epoch: int,
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        nonlocal snapshot_loaded_at, snapshot_value, snapshot_failure
        nonlocal snapshot_failed_at
        try:
            value = await load_snapshot()
        except Exception as exc:
            if epoch == snapshot_epoch:
                snapshot_failure = exc
                snapshot_failed_at = time.monotonic()
            if snapshot_value is None:
                raise
            return snapshot_value

        if epoch == snapshot_epoch:
            snapshot_value = value
            snapshot_loaded_at = time.monotonic()
            snapshot_failure = None
            snapshot_failed_at = 0.0
        return value

    def consume_refresh_exception(task: asyncio.Task[Any]) -> None:
        if not task.cancelled():
            task.exception()

    async def queue_snapshot_value() -> tuple[dict[str, Any], dict[str, Path]]:
        nonlocal snapshot_failure, snapshot_failed_at, snapshot_refresh
        nonlocal snapshot_loaded_at, snapshot_value
        snapshot_signature()
        now = time.monotonic()

        if snapshot_value is not None and now - snapshot_loaded_at < QUEUE_CACHE_TTL:
            return snapshot_value
        if snapshot_failure is not None and now - snapshot_failed_at < 1.0:
            if snapshot_value is not None:
                return snapshot_value
            raise snapshot_failure

        if snapshot_refresh is None or snapshot_refresh.done():
            snapshot_refresh = asyncio.create_task(refresh_snapshot(snapshot_epoch))
            snapshot_refresh.add_done_callback(consume_refresh_exception)
        if (
            snapshot_value is None
            and sources.generation is not None
            and not (sources.persisted and sources.persisted())
        ):
            return _empty_queue_snapshot(), {}
        refresh = snapshot_refresh
        if snapshot_value is not None:
            await asyncio.sleep(0)
            return snapshot_value
        return await asyncio.shield(refresh)

    async def prewarm() -> None:
        if activity_reader is not None:
            await activity_reader()
        await queue_snapshot_value()
        if snapshot_refresh is not None:
            await asyncio.shield(snapshot_refresh)

    async def queue_snapshot(request: Request) -> JSONResponse:
        try:
            snapshot, _ = await queue_snapshot_value()
        except Exception as exc:  # noqa: BLE001 - keep the read route available
            logger.warning("Could not read queue snapshot: %s", exc)
            snapshot = _empty_queue_snapshot()
            snapshot["degraded"] = True
        return JSONResponse(snapshot)

    async def move(request: Request) -> JSONResponse:
        nonlocal snapshot_epoch, snapshot_loaded_at
        body = await _body(request)
        if (
            body is None
            or not isinstance(body.get("plan"), str)
            or not isinstance(body.get("direction"), str)
        ):
            return JSONResponse(
                {"error": "plan and direction are required"}, status_code=400
            )
        # Match GET's stale-while-revalidate membership; the persisted order is
        # patched into this snapshot below before it can be served stale.
        current_snapshot = snapshot_value
        if current_snapshot is None:
            categories, plan_files = await move_categories()
        else:
            snapshot, plan_files = current_snapshot
            categories = {
                item["id"]: [row["id"] for row in item["waiting"]]
                for item in snapshot["categories"]
            }
        category_id = next(
            (key for key, ids in categories.items() if body["plan"] in ids), None
        )
        if category_id is None:
            return JSONResponse(
                {"error": "plan is not waiting"},
                status_code=400 if body["plan"] in plan_files else 404,
            )
        snapshot_epoch += 1
        snapshot_loaded_at = 0.0
        try:
            updated_order = await asyncio.to_thread(
                move_order,
                working_dir / "queue-order.json",
                categories,
                category_id,
                body["plan"],
                body["direction"],
            )
        except KeyError:
            return JSONResponse({"error": "plan not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if snapshot_value is not None:
            snapshot, _ = snapshot_value
            _patch_snapshot_order(snapshot, category_id, updated_order[category_id])
        return JSONResponse(
            {"category": category_id, "order": updated_order[category_id]}
        )

    async def move_categories() -> tuple[dict[str, list[str]], dict[str, Path]]:
        statuses, bindings = (
            sources.queue_inputs()
            if sources.queue_inputs
            else (_plan_status(cli), _bindings(cli))
        )
        statuses = statuses if isinstance(statuses, dict) else {}
        status_plans = flatten_plans(statuses.get("plans", []))
        plans, plan_files, frontmatter, _ = _plan_metadata(
            working_dir,
            status_plans,
            getattr(cli, "env", None),
            sources.records() if sources.records is not None else None,
        )
        activity = await activity_reader() if activity_reader else {}
        active_plans = activity.get("plans", []) if isinstance(activity, dict) else []
        agents = (
            activity.get("activity_agents", []) if isinstance(activity, dict) else []
        )
        active_by_id = {
            str(row.get("id")): row for row in active_plans if isinstance(row, dict)
        }
        titles = _queue_orchestrator_titles(plans, active_by_id, bindings, agents)
        all_categories = _categories(plans, frontmatter, titles)
        rows_by_id = {str(row.get("id")): row for row in plans if row.get("id")}
        valid_ids = {plan_id for ids in all_categories.values() for plan_id in ids}
        activity_by_id = {
            str(row["id"]): _plan_activity_for_queue(row, active_by_id, agents)
            for row in plans
            if row.get("id") and str(row["id"]) in valid_ids
        }
        waiting_categories = {
            category: [
                plan_id
                for plan_id in ids
                if _is_waiting_plan(
                    plan_id, rows_by_id, plan_files, frontmatter, activity_by_id
                )
            ]
            for category, ids in all_categories.items()
        }
        return waiting_categories, plan_files

    async def plan_detail(request: Request) -> JSONResponse:
        plan_id = request.path_params["plan_id"]
        if sources.detail is not None:
            detail = await asyncio.to_thread(sources.detail, plan_id)
            if detail is None:
                if sources.ready is not None and not sources.ready():
                    return JSONResponse(
                        {"error": "plans index is rebuilding"}, status_code=503
                    )
                return JSONResponse({"error": "plan not found"}, status_code=404)
            record, records = detail
        else:
            records = await asyncio.to_thread(_plan_records, working_dir)
            record = _queue_plan_record(working_dir, plan_id, records)
        if record is None:
            return JSONResponse({"error": "plan not found"}, status_code=404)
        projection = await asyncio.to_thread(
            _plan_detail_record, record, plan_id, records
        )
        return JSONResponse(projection)

    async def plans_list(request: Request) -> JSONResponse:
        if sources.records is not None:
            records = await asyncio.to_thread(sources.records)
        else:
            records = await asyncio.to_thread(_plan_records, working_dir)
        records = tuple(record for record in records if record.artifact_type == "plan")
        fields_by_path = _plan_fields_by_path(records)
        plans = [
            {
                "id": Path(record.path).parent.name,
                "title": record.fields.get("title") or Path(record.path).parent.name,
                "label": record.fields.get("label")
                or record.fields.get("title")
                or Path(record.path).parent.name,
            }
            for record in records
        ]
        categories = _categories(
            plans,
            {
                Path(record.path).parent.name: fields_by_path[Path(record.path)]
                for record in records
            },
        )
        order = read_order(working_dir / "queue-order.json", categories)
        fields_by_id = {
            Path(record.path).parent.name: fields_by_path[Path(record.path)]
            for record in records
        }
        queued_ids = [
            plan_id
            for category_ids in order.values()
            for plan_id in category_ids
            if fields_by_id[plan_id].get("status") == "backlog"
        ]
        positions = {
            plan_id: position for position, plan_id in enumerate(queued_ids, start=1)
        }
        result = []
        for record, plan in zip(records, plans, strict=True):
            fields = fields_by_path[Path(record.path)]
            raw_status = str(fields.get("status", "unknown")).lower()
            comments = read_comments(Path(record.path).parent / "comments.jsonl")
            open_comments = sum(comment.get("state") == "open" for comment in comments)
            status = {
                "active": "in_progress",
                "backlog": "queued",
                "blocked": "blocked",
                "completed": "done",
                "cancelled": "done",
            }.get(
                raw_status,
                "needs_review",
            )
            plan_id = plan["id"]
            result.append(
                {
                    "id": plan_id,
                    "title": plan["title"],
                    "label": plan["label"],
                    "status": status,
                    "queue_position": (
                        positions.get(plan_id) if status == "queued" else None
                    ),
                    "open_comments": open_comments,
                    "updated": datetime.fromtimestamp(
                        max([record.mtime, *(task.mtime for task in record.tasks)]), UTC
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        return JSONResponse(result)

    async def add_comment(request: Request) -> JSONResponse:
        plan_id = request.path_params["plan_id"]
        record = await asyncio.to_thread(_plan_record, working_dir, plan_id)
        if record is None:
            return JSONResponse({"error": "plan not found"}, status_code=404)
        path = Path(record.path)
        body = await _body(request)
        target = body.get("target") if body else None
        text = body.get("text") if body else None
        if not isinstance(target, str) or not isinstance(text, str) or not text.strip():
            return JSONResponse(
                {"error": "target and non-empty text are required"}, status_code=400
            )
        if target != "plan" and target not in {task.id for task in record.tasks}:
            return JSONResponse({"error": "task not found"}, status_code=404)
        bindings = await asyncio.to_thread(_bindings, cli)
        bound = _bound_address(plan_id, bindings)
        kind = "sent" if bound else "stored"
        identity = request.scope.get("bot_identity")
        actor = identity.actor if identity is not None else "main"
        comment = {
            "id": str(uuid.uuid4()),
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "target": target,
            "text": text.strip(),
            "state": "open",
            "kind": kind,
            "actor": actor,
            "sender": "manager" if identity is not None else "main",
        }
        if kind == "sent":
            sender = getattr(cli, "send", None)
            if not callable(sender):
                return JSONResponse(
                    {"error": "running plan has no deliverable address"},
                    status_code=502,
                )
            try:
                await asyncio.to_thread(
                    sender,
                    sender=comment["sender"],
                    recipient=bound,
                    kind="info",
                    text=f"Comment on {target}: {comment['text']}",
                    notes=str(path),
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as exc:
                return JSONResponse(
                    {"error": f"comment delivery failed: {type(exc).__name__}"},
                    status_code=502,
                )
        await asyncio.to_thread(append_event, path.parent / "comments.jsonl", comment)
        return JSONResponse(
            {"comment": _comment_api_projection(comment)},
            status_code=201,
        )

    async def resolve_comment(request: Request) -> JSONResponse:
        plan_id = request.path_params["plan_id"]
        comment_id = request.path_params["comment_id"]
        record = await asyncio.to_thread(_plan_record, working_dir, plan_id)
        if record is None:
            return JSONResponse({"error": "plan not found"}, status_code=404)
        body = await _body(request)
        state = body.get("state") if body else None
        if state not in ("open", "resolved"):
            return JSONResponse(
                {"error": "state must be open or resolved"}, status_code=400
            )
        path = Path(record.path).parent / "comments.jsonl"
        comments = await asyncio.to_thread(read_comments, path)
        comment = next((row for row in comments if row.get("id") == comment_id), None)
        if comment is None:
            return JSONResponse({"error": "comment not found"}, status_code=404)
        event = {
            "id": comment_id,
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "state": state,
        }
        await asyncio.to_thread(append_event, path, event)
        return JSONResponse(
            {"comment": _comment_api_projection(comment | {"state": state})}
        )

    queue_snapshot.prewarm = prewarm  # type: ignore[attr-defined]
    return [
        Route("/api/plans", plans_list),
        Route("/api/queue", queue_snapshot),
        Route("/api/queue/move", move, methods=["POST"]),
        Route("/api/plans/{plan_id:str}", plan_detail),
        Route("/api/plans/{plan_id:str}/comments", add_comment, methods=["POST"]),
        Route(
            "/api/plans/{plan_id:str}/comments/{comment_id:str}",
            resolve_comment,
            methods=["POST"],
        ),
    ]


def _plan_detail_record(
    record: Any, plan_id: str, records: tuple[Any, ...]
) -> dict[str, Any]:
    path = Path(record.path)
    text = record.raw.decode("utf-8")
    fields = parse_frontmatter(text)
    tasks = [
        {
            "id": task.id,
            "title": task_fields.get("title", Path(task.path).stem),
            "status": task_fields.get("status", "todo"),
            "acceptance_criteria": task_acceptance(task.raw.decode("utf-8")),
        }
        for task in record.tasks
        if (task_fields := parse_frontmatter(task.raw.decode("utf-8"))).get("type")
        == "task"
    ]
    group_name = _resolved_group_from_fields(path, _plan_fields_by_path(records))
    plan_dir = path.parent
    note_files = list(plan_dir.glob("notes/*.md"))
    review_files = list(plan_dir.glob("review*.md")) + list(
        plan_dir.glob("notes/review*.md")
    )
    return {
        "id": plan_id,
        "title": fields.get("title", plan_id),
        "label": fields.get("label") or fields.get("title") or plan_id,
        "group_name": group_name,
        "status": fields.get("status", "unknown"),
        "plan_text": text,
        "tasks": tasks,
        "notes_status": "present" if note_files else "none",
        "review_status": "present" if review_files else "none",
        "comments": [
            _comment_api_projection(comment)
            for comment in read_comments(plan_dir / "comments.jsonl")
        ],
    }


def _comment_api_projection(comment: dict[str, Any]) -> dict[str, Any]:
    return comment | {"kind": "delivered"} if comment.get("kind") == "sent" else comment


def _plan_status(cli: Any) -> dict[str, Any]:
    reader = getattr(cli, "read_plan_status", None)
    value = reader() if callable(reader) else {}
    return value if isinstance(value, dict) else {}


def _is_waiting_plan(
    plan_id: str,
    rows_by_id: dict[str, dict[str, Any]],
    plan_files: dict[str, Path],
    frontmatter: dict[str, dict[str, str]],
    activity_by_id: dict[str, str],
) -> bool:
    return (
        plan_id in rows_by_id
        and plan_id in plan_files
        and frontmatter.get(plan_id, {}).get("status") == "backlog"
        and activity_by_id.get(plan_id) == "backlog"
    )


def _patch_snapshot_order(
    snapshot: dict[str, Any], category_id: str, order: list[str]
) -> None:
    category = next(
        (item for item in snapshot["categories"] if item["id"] == category_id), None
    )
    if category is None:
        return
    rows_by_id = {row["id"]: row for row in category["waiting"]}
    category["waiting"] = [
        rows_by_id[plan_id] for plan_id in order if plan_id in rows_by_id
    ]
    category["priority_set"] = True
    category["next_up"] = category["waiting"][0]["id"] if category["waiting"] else None


def _bindings(cli: Any) -> list[dict[str, Any]]:
    reader = getattr(cli, "read_address_bindings", None)
    value = reader() if callable(reader) else []
    return (
        [row for row in value if isinstance(row, dict)]
        if isinstance(value, list)
        else []
    )


def _plan_activity_for_queue(
    row: dict[str, Any],
    active_by_id: dict[str, dict[str, Any]],
    agents: list[dict[str, Any]],
) -> str:
    plan_id = str(row.get("id", ""))
    active = active_by_id.get(plan_id, {})
    activity = active.get("activity")
    if activity in {
        "running",
        "waiting",
        "stalled",
        "idle",
        "backlog",
        "blocked",
        "done",
        "unknown",
    }:
        return str(activity)
    plan = row | active
    orchestrator_status = str(plan.get("agent_status", "")).lower()
    orchestrator = (
        {}
        if orchestrator_status in {"", "archived", "closed", "missing"}
        else {
            "id": plan.get("agent_id"),
            "status": orchestrator_status,
            "lastActivity": plan.get("last_activity"),
        }
    )
    return plan_activity(
        plan,
        agents,
        orchestrator,
    )["activity"]


def _is_live_orchestrator(status: Any) -> bool:
    return str(status or "").lower() in {"running", "active", "idle", "error"}


def _bound_address(plan_id: str, bindings: list[dict[str, Any]]) -> str | None:
    return next(
        (
            str(item["address"])
            for item in bindings
            if item.get("address") == plan_id or item.get("plan_id") == plan_id
            if item.get("address")
        ),
        None,
    )


def _categories(
    plans: list[dict[str, Any]],
    frontmatter: dict[str, dict[str, str]],
    orchestrator_titles: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    result = {**{category: [] for category in CATEGORY_LIMITS}, UNCATEGORIZED: []}
    titles = orchestrator_titles or {}
    for row in plans:
        plan_id = str(row.get("id", ""))
        if plan_id:
            try:
                category = category_for_plan(
                    plan_id,
                    frontmatter.get(plan_id, {}).get("category")
                    or _category_from_orchestrator_title(titles.get(plan_id, "")),
                )
                if category not in result:
                    result[category] = []
                result[category].append(plan_id)
            except ValueError:
                continue
    return {key: sorted(value) for key, value in result.items()}


def _orchestrator_from_title(title: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"Orchestrator:\s*(.+)\s+\((new-feature|fixes|friction)\)",
        title.strip(),
        re.IGNORECASE,
    )
    return (match.group(1).strip(), match.group(2).lower()) if match else None


def _category_from_orchestrator_title(title: str) -> str | None:
    parsed = _orchestrator_from_title(title)
    return parsed[1] if parsed else None


def _queue_orchestrator_titles(
    plans: list[dict[str, Any]],
    active_by_id: dict[str, dict[str, Any]],
    bindings: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> dict[str, str]:
    agents_by_id = {
        str(agent.get("id")): agent
        for item in agents
        if isinstance(item, dict)
        for agent in [item.get("agent", item)]
        if isinstance(agent, dict) and agent.get("id")
    }
    plan_ids = [str(row.get("id")) for row in plans if row.get("id")]
    titles: dict[str, str] = {}
    for plan_id in plan_ids:
        plan = active_by_id.get(plan_id, {})
        title = next(
            (
                candidate
                for candidate in (
                    plan.get("orchestrator_title"),
                    plan.get("agent_title"),
                    plan.get("title"),
                )
                if isinstance(candidate, str) and _orchestrator_from_title(candidate)
            ),
            None,
        )
        if title is None:
            agent = agents_by_id.get(str(plan.get("agent_id", "")), {})
            title = agent.get("title") if isinstance(agent.get("title"), str) else ""
        if isinstance(title, str) and _orchestrator_from_title(title):
            titles[plan_id] = title

    for binding in bindings:
        address = binding.get("address")
        if not isinstance(address, str):
            continue
        agent_id = wake_agent_id(binding.get("wake_context"))
        agent = agents_by_id.get(str(agent_id), {})
        title = agent.get("title")
        if not isinstance(title, str):
            continue
        parsed = _orchestrator_from_title(title)
        if parsed is None:
            continue
        plan_id = plan_id_for_address(address, plans, bindings)
        if plan_id:
            titles.setdefault(plan_id, title)
    return titles


def _hidden_plans(
    plans: list[dict[str, Any]],
    frontmatter: dict[str, dict[str, str]],
    activity_by_id: dict[str, str],
) -> list[dict[str, str]]:
    rows_by_id = {str(row.get("id")): row for row in plans if row.get("id")}
    hidden: dict[str, dict[str, str]] = {}

    def add(plan_id: str, title: str, status: str, reason: str) -> None:
        plan = rows_by_id.get(plan_id, {})
        hidden[plan_id] = {
            "id": plan_id,
            "title": title or plan_id,
            "label": str(plan.get("label") or title or plan_id),
            "group_name": str(plan.get("group_name") or ""),
            "status": status or "unknown",
            "reason": reason,
        }

    for plan_id, row in rows_by_id.items():
        status = str(
            frontmatter.get(plan_id, {}).get("status")
            or row.get("status")
            or row.get("state")
            or "unknown"
        )
        if activity_by_id.get(plan_id) in {
            "done",
            "completed",
            "concluded",
            "cancelled",
        }:
            add(plan_id, str(row.get("title", "")), status, "concluded")
        elif activity_by_id.get(plan_id) in {
            "running",
            "waiting",
            "stalled",
            "idle",
            "blocked",
        }:
            add(plan_id, str(row.get("title", "")), status, "active")
    return [hidden[plan_id] for plan_id in sorted(hidden)]


def _readiness(
    plan_file: Path, open_comments: int, fields: dict[str, str]
) -> dict[str, Any]:
    task_count = sum(1 for _ in (plan_file.parent / "tasks").glob("*.md"))
    task_count += _inline_task_count(plan_file.read_text(encoding="utf-8"))
    return {
        "readiness": _readiness_label(fields, open_comments, task_count),
        "task_count": task_count,
    }


def _inline_task_count(content: str) -> int:
    match = re.search(r"(?im)^## Tasks\s*$", content)
    if match is None:
        return 0
    section = content[match.end() :]
    section = re.split(r"(?m)^## ", section, maxsplit=1)[0]
    return sum(
        bool(line.strip()) and line.strip().lower() not in {"(none)", "n/a"}
        for line in section.splitlines()
        if re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line)
    )


def _readiness_label(
    fields: dict[str, str], open_comments: int, task_count: int
) -> str:
    status = fields.get("status", "").lower()
    title = fields.get("title", "").lower()
    if re.search(r"\bheld\b", status) or re.search(r"\bheld\b", title):
        return "held"
    if not task_count:
        return "draft"
    if open_comments or not fields.get("reviewed_commit"):
        return "needs-review"
    return "ready" if status == "backlog" else "needs-review"


def _plan_metadata(
    working_dir: Path,
    plans: list[dict[str, Any]],
    environment: dict[str, str] | None = None,
    indexed_records: tuple[Any, ...] | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Path],
    dict[str, dict[str, str]],
    dict[str, int],
]:
    records = tuple(
        record
        for record in (
            indexed_records
            if indexed_records is not None
            else _plan_repository(working_dir, environment).list().records
        )
        if record.artifact_type == "plan"
    )
    records_by_name: dict[str, list[Any]] = defaultdict(list)
    for record in records:
        records_by_name[Path(record.path).parent.name].append(record)
    records_by_id = {
        plan_id: matches[0]
        for plan_id, matches in records_by_name.items()
        if len(matches) == 1
    }
    plan_files = {
        plan_id: Path(record.path) for plan_id, record in records_by_id.items()
    }
    fields_by_path = _plan_fields_by_path(records)
    frontmatter: dict[str, dict[str, str]] = {}
    open_counts: dict[str, int] = {}
    rows_by_id = {str(row.get("id")): row for row in plans if row.get("id")}
    for plan_id, record in records_by_id.items():
        path = Path(record.path)
        fields = fields_by_path[path]
        frontmatter[plan_id] = fields
        open_counts[plan_id] = sum(
            comment.get("state") == "open"
            for comment in read_comments(path.parent / "comments.jsonl")
        )
    merged = []
    for plan_id, fields in frontmatter.items():
        path = plan_files[plan_id]
        status_title = rows_by_id.get(plan_id, {}).get("title")
        merged.append(
            {
                "id": plan_id,
                "title": fields.get("title", plan_id),
                "label": (
                    fields.get("label")
                    or fields.get("title")
                    or status_title
                    or plan_id
                ),
                "purpose": rows_by_id.get(plan_id, {}).get("purpose", ""),
                "group_name": _resolved_group_from_fields(path, fields_by_path),
                "status": fields.get("status", "unknown"),
                "frontmatter_status": fields.get("status", "unknown"),
                **rows_by_id.get(plan_id, {}),
            }
        )
    merged.extend(
        row for plan_id, row in rows_by_id.items() if plan_id not in plan_files
    )
    return merged, plan_files, frontmatter, open_counts


def _plan_fields_by_path(records: tuple[Any, ...]) -> dict[Path, dict[str, str]]:
    return {
        Path(record.path): parse_frontmatter(record.raw.decode("utf-8"))
        for record in records
    }


def _resolved_group_from_fields(
    path: Path, fields_by_path: dict[Path, dict[str, str]]
) -> str:
    plans_root = next(
        (parent for parent in path.parents if parent.name == "plans"), None
    )
    if plans_root is None:
        return ""
    ancestors = [
        parent / "plan.md" for parent in path.parent.parents if parent != plans_root
    ]
    inherited = ""
    for ancestor in reversed(ancestors):
        inherited = _resolve_group(
            fields_by_path.get(ancestor, {}).get("group"), inherited
        )
    return _resolve_group(fields_by_path.get(path, {}).get("group"), inherited)


def _resolve_group(own: object, parent_resolved: str) -> str:
    """Mirror workflow's resolve_group without adding a runner dependency."""
    return own.strip() if isinstance(own, str) and own.strip() else parent_resolved


def _plan_record(working_dir: Path, plan_id: str) -> Any | None:
    if not plan_id or Path(plan_id).name != plan_id or plan_id in {".", ".."}:
        return None
    records = _plan_records(working_dir)
    return _queue_plan_record(working_dir, plan_id, records)


def _plan_records(
    working_dir: Path, environment: dict[str, str] | None = None
) -> tuple[Any, ...]:
    return tuple(
        record
        for record in _plan_repository(working_dir, environment).list().records
        if record.artifact_type == "plan"
    )


def _queue_plan_record(
    working_dir: Path, plan_id: str, records: tuple[Any, ...]
) -> Any | None:
    if not plan_id or Path(plan_id).name != plan_id or plan_id in {".", ".."}:
        return None
    plans_root = working_dir.expanduser().resolve() / "plans"
    direct_path = plans_root / plan_id / "plan.md"
    direct = next(
        (record for record in records if Path(record.path) == direct_path), None
    )
    if direct is not None:
        return direct
    matches = tuple(
        record for record in records if Path(record.path).parent.name == plan_id
    )
    return matches[0] if len(matches) == 1 else None


def _plan_repository(working_dir: Path, environment: dict[str, str] | None = None):
    return shared_plans_repository(working_dir, environment)


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        value = json.loads(await request.body())
    except json.JSONDecodeError, UnicodeDecodeError:
        return None
    return value if isinstance(value, dict) else None
