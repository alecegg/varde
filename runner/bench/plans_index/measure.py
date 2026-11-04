"""Measure runner plan routes against an isolated copy of a working tree."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.routing import Route
from varde_data.backends.sqlite.plans_index import SqlitePlansIndex
from varde_runner.config import default_toml
from varde_runner.relay import RelayWorker
from varde_runner.varde_cli import VardeCLI
from varde_runner.web import create_app

REPO = Path(__file__).resolve().parents[3]
DEFAULT_WORKING = Path(
    os.environ.get(
        "VARDE_WORKING_DIR",
        Path.home() / "source/agent-memory/projects/varde-py/working",
    )
)
ROUTES = ("/api/orchestrators", "/api/queue", "/api/plans")
IGNORED_CLOCK_FIELDS = {"now_at", "newest_activity", "last_event_at"}
WARM_RUNS = 50


class _AgentReader:
    async def target_idle_status(
        self, _agent_id: str, _harness: str | None = None
    ) -> str:
        return "idle"


class _RelayCommand:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def bindings(self) -> list[dict[str, Any]]:
        return []

    async def status(self) -> dict[str, list[object]]:
        return {"mailmen": []}

    async def issue_and_bind(self, _session_id: str) -> str:
        return "stub-identity"

    async def issue_and_bind_superseding(self, _session_id: str) -> str:
        return "stub-identity"

    async def renew(self, _action_id: str) -> dict[str, str]:
        return {"status": "ok"}

    async def wait(self, _identity: str) -> dict[str, Any]:
        await self.release.wait()
        return {"actions": []}

    async def confirm(
        self, _action_id: str, _result: str, _evidence: str, _identity: str
    ) -> None:
        return None

    async def end(self, _identity: str) -> None:
        return None

    async def unbind(self, _session_id: str) -> None:
        return None


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical(item)
            for key, item in value.items()
            if key not in IGNORED_CLOCK_FIELDS
        }
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


async def _get(app: Any, path: str) -> tuple[int, dict[str, Any]]:
    route_path = path
    if path.startswith("/api/plans/"):
        route_path = "/api/plans/{plan_id:str}"
    route = next(
        item
        for item in app.routes
        if isinstance(item, Route) and item.path == route_path
    )
    params = {"plan_id": path.rsplit("/", 1)[-1]} if route_path != path else {}
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "server": ("127.0.0.1", 80),
            "client": ("127.0.0.1", 1),
            "app": app,
            "path_params": params,
        }
    )
    response = await route.endpoint(request)
    return response.status_code, json.loads(response.body)


async def _run_case(working: Path, route: str, runs: int) -> dict[str, Any]:
    working = working.resolve()
    process_started = time.perf_counter()
    config = working.parent / "config"
    config.mkdir(exist_ok=True)
    (config / "runner.toml").write_text(default_toml(), encoding="utf-8")
    os.environ["VARDE_CONFIG_DIR"] = str(config)
    os.environ["VARDE_RUNNER_CONFIG_DIR"] = str(config)
    os.environ["VARDE_WORKING_DIR"] = str(working)
    app = create_app(
        data_dir=working.parent / "runner-data",
        cli=VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)}),
        agents=list,
    )
    dashboard = app.state.dashboard
    dashboard.plan_reads.start()
    first_started = time.perf_counter()
    first_status, first_body = await _get(app, route)
    first_ms = (time.perf_counter() - first_started) * 1_000
    ready_deadline = time.perf_counter() + 120
    while dashboard.plan_reads._snapshot() is None:
        if time.perf_counter() >= ready_deadline:
            dashboard.plan_reads.stop()
            raise TimeoutError("plan refresh did not publish data within 120 seconds")
        await asyncio.sleep(0.005)
    await dashboard.orchestrators()
    queue_route = next(
        item
        for item in app.routes
        if isinstance(item, Route) and item.path == "/api/queue"
    )
    await queue_route.endpoint.prewarm()
    ready_ms = (time.perf_counter() - process_started) * 1_000
    samples = []
    bodies = []
    statuses = []
    for _ in range(runs):
        started = time.perf_counter()
        status, body = await _get(app, route)
        bodies.append(body)
        statuses.append(status)
        samples.append((time.perf_counter() - started) * 1_000)
    dashboard.plan_reads.stop()
    return {
        "first_ms": first_ms,
        "first_status": first_status,
        "warm_status": statuses[-1],
        "ready_ms": ready_ms,
        "first_body": first_body,
        "first_has_plan_data": _has_plan_data(first_body),
        "warm_median_ms": statistics.median(samples),
        "warm_p95_ms": sorted(samples)[math.ceil(0.95 * len(samples)) - 1],
        "body": _canonical(bodies[-1]),
    }


def _has_plan_data(value: Any) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("plans"), list) and value["plans"]:
            return True
        if "id" in value and "status" in value and "title" in value:
            return True
        return any(_has_plan_data(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_plan_data(item) for item in value)
    return False


async def _relay_waiting_ms() -> float:
    command = _RelayCommand()
    worker = RelayWorker(
        command,
        _AgentReader(),
        plan_watch=lambda _stale: {"plans": [], "events": []},
    )
    started = time.perf_counter()
    task = asyncio.create_task(worker.run())
    try:
        while worker.state != "waiting":
            await asyncio.sleep(0.001)
        return (time.perf_counter() - started) * 1_000
    finally:
        worker._stop = True
        command.release.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _concurrent_cold_queue(working: Path) -> tuple[float, list[int]]:
    config = working.parent / "concurrent-config"
    config.mkdir(exist_ok=True)
    (config / "runner.toml").write_text(default_toml(), encoding="utf-8")
    os.environ["VARDE_CONFIG_DIR"] = str(config)
    os.environ["VARDE_RUNNER_CONFIG_DIR"] = str(config)
    os.environ["VARDE_WORKING_DIR"] = str(working)
    app = create_app(
        data_dir=working.parent / "concurrent-runner-data",
        cli=VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)}),
        agents=list,
    )
    dashboard = app.state.dashboard
    dashboard.plan_reads.start()
    started = time.perf_counter()
    route = "/api/queue"
    try:
        results = await asyncio.gather(*(_get(app, route) for _ in range(16)))
        statuses = [status for status, _ in results]
        return (time.perf_counter() - started) * 1_000, statuses
    finally:
        dashboard.plan_reads.stop()


def _child(working: Path, route: str, runs: int) -> None:
    result = asyncio.run(_run_case(working, route, runs))
    print(json.dumps(result, separators=(",", ":")))


def _fresh_process(working: Path, route: str, runs: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        str(working),
        route,
        str(runs),
    ]
    result = subprocess.run(  # noqa: S603 - executes this harness with fixed arguments
        command, check=False, capture_output=True, text=True, cwd=REPO
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def _copy_working(source: Path, target: Path) -> None:
    target.mkdir(parents=True)
    shutil.copytree(source / "plans", target / "plans", symlinks=False)
    for name in ("plan-now", "reviews", "queue-order.json"):
        item = source / name
        if item.is_dir():
            shutil.copytree(item, target / name, symlinks=False)
        elif item.is_file():
            shutil.copy2(item, target / name, follow_symlinks=True)
    for name in ("plan-now", "inbox", "decisions"):
        cache_source = source / ".cache" / name
        if cache_source.exists():
            shutil.copytree(
                cache_source,
                target / ".cache" / name,
                symlinks=False,
            )


def _print_results(rows: list[tuple[str, str, dict[str, Any]]]) -> None:
    print(
        "Route | Scenario | first ms | first data | data ready ms | "
        "first HTTP | warm HTTP | warm median ms | warm p95 ms"
    )
    for route, scenario, result in rows:
        print(
            f"{route} | {scenario} | {result['first_ms']:.1f} | "
            f"{result['first_has_plan_data']} | "
            f"{result['ready_ms']:.1f} | {result['first_status']} | "
            f"{result['warm_status']} | "
            f"{result['warm_median_ms']:.2f} | "
            f"{result['warm_p95_ms']:.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, default=DEFAULT_WORKING)
    parser.add_argument("--child", nargs=3, metavar=("WORKING", "ROUTE", "RUNS"))
    args = parser.parse_args()
    if args.child:
        _child(Path(args.child[0]), args.child[1], int(args.child[2]))
        return
    with tempfile.TemporaryDirectory(prefix="varde-plans-measure-") as temporary:
        working = Path(temporary) / "working"
        _copy_working(args.working.resolve(), working)
        SqlitePlansIndex(working.resolve()).refresh()
        rows = []
        output_by_case: dict[tuple[str, str], Any] = {}
        for route in ROUTES:
            path = route
            if route == "/api/plans":
                first_plan = next(
                    (
                        Path(str(row["path"])).parent.name
                        for row in SqlitePlansIndex(working.resolve()).plan_rows()
                        if row.get("artifact_type") == "plan"
                        and not row.get("archived")
                    ),
                    None,
                )
                if first_plan:
                    path = f"/api/plans/{first_plan}"
            for scenario in ("persisted index", "deleted index / rebuild"):
                index_path = working / ".cache" / "plans-read-index.sqlite3"
                if scenario == "deleted index / rebuild":
                    index_path.unlink(missing_ok=True)
                    Path(f"{index_path}-wal").unlink(missing_ok=True)
                    Path(f"{index_path}-shm").unlink(missing_ok=True)
                result = _fresh_process(working, path, WARM_RUNS)
                rows.append((route, scenario, result))
                output_by_case[(route, scenario)] = result["body"]
        _print_results(rows)
        print("Delete-index rebuild output equality:")
        for route in ROUTES:
            persisted = output_by_case[(route, "persisted index")]
            rebuilt = output_by_case[(route, "deleted index / rebuild")]
            print(f"  {route}: {persisted == rebuilt}")
        print(
            "First response is the available snapshot; "
            "data-ready time includes startup refresh."
        )
        print(
            f"RelayWorker start to waiting: {asyncio.run(_relay_waiting_ms()):.2f} ms"
        )
        index_path = working / ".cache" / "plans-read-index.sqlite3"
        index_path.unlink(missing_ok=True)
        Path(f"{index_path}-wal").unlink(missing_ok=True)
        Path(f"{index_path}-shm").unlink(missing_ok=True)
        concurrent_ms, statuses = asyncio.run(_concurrent_cold_queue(working))
        print(
            "16 concurrent cold queue requests: "
            f"{concurrent_ms:.2f} ms, statuses={sorted(set(statuses))}"
        )


if __name__ == "__main__":
    main()
