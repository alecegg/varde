from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from starlette.requests import Request
from varde_data.queue import open_queue
from varde_data.records.queue import QueueItemInput
from varde_runner.web.role_queues_route import create_role_queues_route


def test_role_queues_returns_claims_budget_and_metrics(tmp_path: Path) -> None:
    repo = open_queue(tmp_path, "memory")
    repo.enqueue(
        QueueItemInput(
            "build-1",
            str(tmp_path / "plans" / "p1"),
            role="builder",
            queue_name="roles/p1",
            extra={"worktree": "worktrees/build-1"},
        )
    )
    repo.enqueue(
        QueueItemInput(
            "review-1",
            str(tmp_path / "plans" / "p1"),
            role="reviewer",
            queue_name="roles/p1",
        )
    )
    resources = tmp_path / ".cache" / "data" / "resources.json"
    resources.parent.mkdir(parents=True)
    resources.write_text(
        json.dumps(
            {
                "taken_at": datetime.now(UTC).isoformat(),
                "providers": {"alpha": 0.2},
                "rss_mb": 100,
                "cpu_pct": 10,
                "processes": 20,
                "live_workers": 2,
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "runner.toml"
    config.write_text(
        "[queue_budget]\nprovider_max = { alpha = 0.8 }\n"
        "rss_mb_max = 500\ncpu_pct_max = 80\n"
        "processes_max = 100\nglobal_worker_ceiling = 24\n",
        encoding="utf-8",
    )
    route = create_role_queues_route(tmp_path, repo, config_path=config)

    async def request() -> dict:
        response = await route.endpoint(_request())
        return json.loads(response.body)

    result = asyncio.run(request())
    assert [row["role"] for row in result["roles"]] == ["builder", "reviewer"]
    builder = result["roles"][0]
    assert builder["queued"] == 1
    assert builder["claimed"] == 0
    assert builder["ready"] == 1
    assert builder["items"][0]["claimed_by"] is None
    assert result["budget"]["snapshot"]["live_workers"] == 2
    assert result["budget"]["limits"]["global_worker_ceiling"] == 24
    assert result["budget"]["decision"] == {"ok": True, "reason": "within budget"}
    assert result["metrics"]["cycle_seconds"] == {"build-1": None, "review-1": None}


def test_missing_budget_inputs_fail_closed(tmp_path: Path) -> None:
    route = create_role_queues_route(
        tmp_path, open_queue(tmp_path, "memory"), config_path=tmp_path / "runner.toml"
    )

    async def request() -> dict:
        response = await route.endpoint(_request())
        return json.loads(response.body)

    budget = asyncio.run(request())["budget"]
    assert budget["snapshot"] is None
    assert budget["limits"]["global_worker_ceiling"] == 24
    assert budget["decision"] == {"ok": False, "reason": "resource snapshot missing"}


def test_markdown_mode_does_not_create_sqlite_database(tmp_path: Path) -> None:
    database = tmp_path / ".cache" / "data" / "queue.sqlite3"
    route = create_role_queues_route(tmp_path)
    assert not database.exists()

    async def request():
        return await route.endpoint(_request())

    response = asyncio.run(request())
    assert response.status_code == 409
    assert json.loads(response.body) == {
        "error": "role queues unavailable in markdown mode",
        "mode": "markdown",
    }
    assert not database.exists()


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/queue/roles",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )
