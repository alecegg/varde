# pyright: reportArgumentType=false, reportGeneralTypeIssues=false
"""First requests after a restart must not queue behind slow plan reads."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from test_perf_cache import _get_asgi_status
from varde_runner.decisions import DecisionStore
from varde_runner.web.app import create_app

pytestmark = pytest.mark.slow

SLOW_READ_SECONDS = 0.4
SLOW_REBUILD_SECONDS = 1.5
BOUND_SECONDS = 5


def _slow_cli(tmp_path, calls):
    def slow(name, value):
        def read():
            calls.append(name)
            time.sleep(SLOW_READ_SECONDS)
            return value

        return read

    working = tmp_path / "working"
    (working / "plans").mkdir(parents=True)
    return SimpleNamespace(
        cwd=working,
        env={},
        send=lambda *_args, **_kwargs: {},
        read_messages=list,
        read_plan=slow("plan", {"events": []}),
        read_plan_status=slow("status", {"plans": []}),
        read_plan_watch=slow("watch", {"events": []}),
        read_address_bindings=slow("bindings", []),
        read_assigned_plans=slow("assigned", []),
    )


def _app(tmp_path, calls):
    return create_app(
        data_dir=tmp_path / "runner",
        cli=_slow_cli(tmp_path, calls),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
        agents=list,
    )


def _delayed(seconds):
    def read():
        time.sleep(seconds)
        return []

    return read


async def _burst(app, count):
    paths = ["/api/queue", "/api/orchestrators"] * count
    started = time.monotonic()

    async def timed(path):
        status = await _get_asgi_status(app, path)
        return status, time.monotonic() - started

    return await asyncio.gather(*(timed(path) for path in paths))


def test_create_app_does_not_wait_for_plan_watch(tmp_path):
    calls = []
    started = time.monotonic()
    _app(tmp_path, calls)
    assert time.monotonic() - started < SLOW_READ_SECONDS
    assert "watch" not in calls
    assert "plan" not in calls


def test_concurrent_first_requests_finish_during_startup(tmp_path):
    app = _app(tmp_path, [])

    async def run():
        async with app.router.lifespan_context(app):
            results = await _burst(app, 8)
            assert all(status == 200 for status, _ in results)
            assert max(elapsed for _, elapsed in results) < BOUND_SECONDS

    asyncio.run(run())


def test_aged_snapshot_is_served_while_one_refresh_runs(tmp_path):
    calls = []
    app = _app(tmp_path, calls)

    async def run():
        async with app.router.lifespan_context(app):
            await app.state.dashboard.prewarm_task
            dashboard = app.state.dashboard
            dashboard.snapshot_loaded_at -= 10
            app.state.dashboard.cli.read_assigned_plans = _delayed(SLOW_REBUILD_SECONDS)
            calls.clear()
            results = await _burst(app, 8)
            assert all(status == 200 for status, _ in results)
            assert max(elapsed for _, elapsed in results) < SLOW_READ_SECONDS
            await dashboard.snapshot_refresh

    asyncio.run(run())


def test_concurrent_polls_share_one_mailbox_projection(tmp_path):
    app = _app(tmp_path, [])

    async def run():
        async with app.router.lifespan_context(app):
            dashboard = app.state.dashboard
            await dashboard.prewarm_task
            projections = []
            project = dashboard.projector.project

            def slow_project():
                projections.append(True)
                time.sleep(SLOW_REBUILD_SECONDS)
                return project()

            dashboard.projector.project = slow_project
            results = await _burst(app, 8)
            assert all(status == 200 for status, _ in results)
            assert len(projections) <= 2
            assert max(elapsed for _, elapsed in results) < 2 * SLOW_REBUILD_SECONDS + 1

    asyncio.run(run())
