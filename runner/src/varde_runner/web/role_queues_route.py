"""Raw queue rows with budget and metrics for ``GET /api/queue/roles``.

Serves ``QueueRepository`` rows as plain ``QueueItem`` data plus ``budget`` and
``metrics`` from the store, and answers 409 in markdown mode. The queue page
reads the summaries in ``role_queue_route.py`` instead; its consumers are tests
and the unrouted ``RoleQueues.svelte``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.errors import Invalid, WrongMode
from varde_data.queue import open_queue
from varde_data.queue_mode_lock import operation
from varde_data.repos.queue import QueueRepository
from varde_workflow.role_queue_budget import (
    Decision,
    ResourceSnapshot,
    load_limits,
    may_start,
)
from varde_workflow.role_queue_metrics import lane_metrics

from varde_runner.config import config_path as runner_config_path


def _snapshot(path: Path) -> ResourceSnapshot | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ResourceSnapshot(
            datetime.fromisoformat(raw["taken_at"]),
            raw["providers"],
            raw["rss_mb"],
            raw["cpu_pct"],
            raw["processes"],
            raw["live_workers"],
        )
    except OSError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        return None


def _item_payload(item: Any) -> dict[str, Any]:
    return asdict(item)


def create_role_queues_route(
    working_dir: Path,
    repository: QueueRepository | None = None,
    *,
    config_path: Path | None = None,
) -> Route:
    repo = repository
    config = config_path or runner_config_path()
    cache: tuple[object, list[Any]] | None = None

    async def role_queues(_request: Request) -> JSONResponse:
        nonlocal cache, repo
        try:
            with operation(working_dir) as mode:
                if mode != "sqlite" and repo is None:
                    return JSONResponse(
                        {
                            "error": "role queues unavailable in markdown mode",
                            "mode": "markdown",
                        },
                        status_code=409,
                    )
                if repo is None:
                    repo = open_queue(working_dir)
                version = repo.version()
                if cache is None or cache[0] != version:
                    cache = (version, repo.list())
                items = cache[1]
                events = [event for item in items for event in repo.events(item.id)]
        except WrongMode:
            return JSONResponse(
                {
                    "error": "role queues unavailable in markdown mode",
                    "mode": "markdown",
                },
                status_code=409,
            )
        except Invalid as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        limits, reason = load_limits(config)
        snapshot = _snapshot(working_dir / ".cache" / "data" / "resources.json")
        now = datetime.now(UTC)
        decision = (
            may_start(snapshot, limits, now)
            if limits is not None
            else Decision(False, reason)
        )
        roles = sorted({item.role for item in items if item.role})
        role_rows = []
        for role in roles:
            rows = [item for item in items if item.role == role]
            role_rows.append(
                {
                    "role": role,
                    "queued": sum(item.state == "queued" for item in rows),
                    "claimed": sum(
                        item.state in {"claimed", "building", "in_review"}
                        for item in rows
                    ),
                    "ready": sum(
                        item.state == "queued" and decision.ok for item in rows
                    ),
                    "items": [_item_payload(item) for item in rows],
                }
            )

        metrics = lane_metrics(items, events, now)
        return JSONResponse(
            {
                "roles": role_rows,
                "budget": {
                    "snapshot": (
                        asdict(snapshot) | {"taken_at": snapshot.taken_at.isoformat()}
                        if snapshot is not None
                        else None
                    ),
                    "limits": asdict(limits) if limits is not None else None,
                    "decision": asdict(decision),
                },
                "metrics": asdict(metrics),
            }
        )

    return Route("/api/queue/roles", role_queues, methods=["GET"])
