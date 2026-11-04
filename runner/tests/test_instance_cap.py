import asyncio
from pathlib import Path
from typing import cast

import pytest
from fakes.plugin import FakePlugin
from varde_runner.config import KNOWN_HARNESSES, default_toml
from varde_runner.instance_cap import InstanceCapError, live_count, over_cap
from varde_runner.plugins import RunnerCapabilities, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import RunnerPlugin
from varde_runner.supervisor import Supervisor
from varde_runner.workitems import WorkItemStore


def _supervisor(tmp_path: Path, monkeypatch, max_live: int = 8, plugin=None):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = default_toml().replace(
        "max_live_instances = 8", f"max_live_instances = {max_live}"
    )
    (config_dir / "runner.toml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    plugin = plugin or FakePlugin()
    registry = PluginRegistry(KNOWN_HARNESSES)
    for harness in KNOWN_HARNESSES:
        registry.register(harness, cast("RunnerPlugin", plugin))
    return Supervisor(tmp_path / "data", registry), plugin


def _spec(tmp_path: Path) -> SessionSpec:
    return SessionSpec(
        "codex-app-server", "model", "workspace", str(tmp_path), "prompt"
    )


def test_live_count_excludes_completed_and_archived_agents():
    rows = [
        {"lifecycle": "running"},
        {"lifecycle": "starting"},
        {"lifecycle": "completed"},
        {"lifecycle": "archived"},
    ]

    assert live_count(rows) == 2


def test_over_cap_blocks_when_capacity_is_full():
    assert over_cap(2, 2)
    assert not over_cap(1, 2)


def test_start_refuses_when_live_instance_cap_is_reached(tmp_path, monkeypatch):
    supervisor, plugin = _supervisor(tmp_path, monkeypatch, max_live=2)
    for lifecycle in ("running", "starting", "completed", "archived"):
        supervisor.store.create_session(
            lifecycle,
            "codex-app-server",
            {"session_id": lifecycle},
            "builder",
            lifecycle=lifecycle,
        )

    with pytest.raises(InstanceCapError) as raised:
        asyncio.run(supervisor.start_session(_spec(tmp_path), "builder"))

    assert raised.value.live == 2
    assert raised.value.max_live == 2
    assert plugin.started == []


def test_start_below_cap_succeeds(tmp_path, monkeypatch):
    supervisor, plugin = _supervisor(tmp_path, monkeypatch, max_live=2)

    asyncio.run(supervisor.start_session(_spec(tmp_path), "builder"))
    asyncio.run(supervisor.start_session(_spec(tmp_path), "builder"))

    assert len(plugin.started) == 2


def test_parallel_starts_reserve_only_one_slot(tmp_path, monkeypatch):
    class DelayedPlugin(FakePlugin):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def start(self, spec):
            self.entered.set()
            await self.release.wait()
            return await super().start(spec)

    plugin = DelayedPlugin()
    supervisor, _ = _supervisor(tmp_path, monkeypatch, max_live=1, plugin=plugin)

    async def run():
        first = asyncio.create_task(
            supervisor.start_session(_spec(tmp_path), "builder")
        )
        await plugin.entered.wait()
        with pytest.raises(InstanceCapError):
            await supervisor.start_session(_spec(tmp_path), "builder")
        plugin.release.set()
        await first

    asyncio.run(run())
    assert len(plugin.started) == 1


def test_failed_start_releases_reserved_slot(tmp_path, monkeypatch):
    class FailingOncePlugin(FakePlugin):
        fail = True

        async def start(self, spec):
            if self.fail:
                self.fail = False
                raise RuntimeError("start failed")
            return await super().start(spec)

    plugin = FailingOncePlugin()
    supervisor, _ = _supervisor(tmp_path, monkeypatch, max_live=1, plugin=plugin)

    with pytest.raises(RuntimeError, match="start failed"):
        asyncio.run(supervisor.start_session(_spec(tmp_path), "builder"))
    asyncio.run(supervisor.start_session(_spec(tmp_path), "builder"))

    assert len(plugin.started) == 1


def test_planner_start_obeys_live_instance_cap(tmp_path, monkeypatch):
    supervisor, _ = _supervisor(tmp_path, monkeypatch, max_live=1)
    asyncio.run(supervisor.start_session(_spec(tmp_path), "builder"))
    partial_cleanup = []

    async def record_partial_cleanup(*_args):
        partial_cleanup.append(True)

    monkeypatch.setattr(supervisor, "_stop_partial_start", record_partial_cleanup)

    with pytest.raises(InstanceCapError):
        asyncio.run(
            supervisor.start_planner_session(
                "plan-1", tmp_path / "notes.md", str(tmp_path)
            )
        )
    assert partial_cleanup == []


def test_unresumable_planner_restart_excludes_replaced_session(tmp_path, monkeypatch):
    plugin = FakePlugin(RunnerCapabilities(resume=False))
    supervisor, _ = _supervisor(tmp_path, monkeypatch, max_live=1, plugin=plugin)

    async def run():
        work_items = WorkItemStore(supervisor.data_dir)
        item = work_items.create("restart", "planner restart", str(tmp_path))
        old = await supervisor.start_planner_session(
            item.id, Path(item.notes_path), item.project
        )
        work_items.start_planning(item.id, old.session_id)
        work_items.close()

        await supervisor._restart_unresumable_planners()

        recovered = WorkItemStore(supervisor.data_dir)
        current = recovered.get(item.id)
        old_row = supervisor.store.get_session(old.session_id)
        try:
            assert current.planner_session != old.session_id
            assert old_row is not None
            assert old_row["lifecycle"] == "completed"
            assert live_count(supervisor.store.sessions()) == 1
        finally:
            recovered.close()

    asyncio.run(run())


def test_unresumable_planner_restart_logs_cap_refusal(tmp_path, monkeypatch, caplog):
    plugin = FakePlugin(RunnerCapabilities(resume=False))
    supervisor, _ = _supervisor(tmp_path, monkeypatch, max_live=1, plugin=plugin)
    work_items = WorkItemStore(supervisor.data_dir)
    item = work_items.create("restart", "planner restart", str(tmp_path))
    supervisor.store.create_session(
        "old-planner",
        "codex-app-server",
        {"session_id": "remote-old"},
        "planner",
        lifecycle="running",
    )
    work_items.start_planning(item.id, "old-planner")
    work_items.close()

    async def refuse(*_args, **_kwargs):
        raise InstanceCapError(1, 1)

    monkeypatch.setattr(supervisor, "start_planner_session", refuse)
    asyncio.run(supervisor._restart_unresumable_planners())

    assert "cap reached, planner not restarted" in caplog.text
    assert "could not restart planner" not in caplog.text
