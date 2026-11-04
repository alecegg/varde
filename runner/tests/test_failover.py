from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from varde_runner.config import Model, default_toml
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSettings
from varde_runner.plugins.paseo import PaseoPlugin, is_provider_limit_error
from varde_runner.protocol import RunnerPlugin
from varde_runner.supervisor import Supervisor


class FakePlugin:
    capabilities = RunnerCapabilities(resume=True)

    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.specs = []
        self.stopped: list[SessionRef] = []
        self.limit_match = "usage limit"

    async def list_workspaces(self):
        return []

    def is_provider_limit_error(self, exc: BaseException) -> bool:
        return self.limit_match in str(exc).casefold()

    def harness_for_provider(self, provider):
        return {"codex": "codex-app-server"}.get(provider, provider)

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    async def start(self, spec):
        self.specs.append(spec)
        if self.failures:
            raise self.failures.pop(0)
        return SessionRef(spec.provider, f"remote-{spec.model}")

    async def stop(self, ref):
        self.stopped.append(ref)

    async def events(self, ref):
        await asyncio.Event().wait()
        yield

    async def close(self):
        return None


def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "runner.toml"
    path.write_text(default_toml(), encoding="utf-8")
    return path


def test_limit_error_starts_fallback_with_its_own_harness_and_effort(tmp_path):
    async def run():
        primary = FakePlugin([RuntimeError("You've hit your usage limit")])
        fallback = FakePlugin()
        supervisor = Supervisor(
            tmp_path / "data",
            {
                "claude-sdk": cast("RunnerPlugin", primary),
                "opencode-http": cast("RunnerPlugin", fallback),
            },
        )
        session = await supervisor.start_planner_session(
            "item-1", tmp_path / "request.md", "workspace", config_file(tmp_path)
        )
        try:
            assert len(primary.specs) == 1
            assert len(fallback.specs) == 1
            assert fallback.specs[0].provider == "opencode-http"
            assert fallback.specs[0].model == "opencode-go/deepseek-v4.1-flash"
            assert fallback.specs[0].reasoning_effort == "high"
            assert session.provider == "opencode-http"
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_non_paseo_plugin_hook_classifies_limit_for_fallback(tmp_path):
    async def run():
        primary = FakePlugin([RuntimeError("vendor plan exhausted")])
        primary.limit_match = "plan exhausted"
        fallback = FakePlugin()
        supervisor = Supervisor(
            tmp_path / "data", {"claude-sdk": primary, "opencode-http": fallback}
        )
        session = await supervisor.start_planner_session(
            "item-hook", tmp_path / "request.md", "workspace", config_file(tmp_path)
        )
        try:
            assert not primary.failures
            assert len(primary.specs) == 1
            assert len(fallback.specs) == 1
            assert session.provider == "opencode-http"
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_plugin_without_limit_hook_does_not_fail_over(tmp_path):
    async def run():
        primary = FakePlugin([RuntimeError("You've hit your usage limit")])
        cast("Any", primary).is_provider_limit_error = None
        fallback = FakePlugin()
        supervisor = Supervisor(
            tmp_path / "data", {"claude-sdk": primary, "pi": fallback}
        )
        with pytest.raises(RuntimeError, match="usage limit"):
            await supervisor.start_planner_session(
                "item-no-hook",
                tmp_path / "request.md",
                "workspace",
                config_file(tmp_path),
            )
        try:
            assert len(primary.specs) == 1
            assert not fallback.specs
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_disabled_fallback_trigger_does_not_start_fallback(tmp_path):
    async def run():
        config_path = config_file(tmp_path)
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'allow_fallback_only_on = ["provider_limit"]',
                "allow_fallback_only_on = []",
            ),
            encoding="utf-8",
        )
        primary = FakePlugin([RuntimeError("You've hit your usage limit")])
        fallback = FakePlugin()
        supervisor = Supervisor(
            tmp_path / "data",
            {
                "claude-sdk": cast("RunnerPlugin", primary),
                "pi": cast("RunnerPlugin", fallback),
            },
        )
        with pytest.raises(RuntimeError, match="usage limit"):
            await supervisor.start_planner_session(
                "item-no-fallback", tmp_path / "request.md", "workspace", config_path
            )
        try:
            assert len(primary.specs) == 1
            assert not fallback.specs
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_non_limit_error_stops_fallback_chain(tmp_path):
    async def run():
        primary = FakePlugin([RuntimeError("workspace unavailable")])
        fallback = FakePlugin()
        supervisor = Supervisor(
            tmp_path / "data",
            {
                "claude-sdk": cast("RunnerPlugin", primary),
                "pi": cast("RunnerPlugin", fallback),
            },
        )
        with pytest.raises(RuntimeError, match="workspace unavailable"):
            await supervisor.start_planner_session(
                "item-2", tmp_path / "request.md", "workspace", config_file(tmp_path)
            )
        try:
            assert len(primary.specs) == 1
            assert not fallback.specs
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_listed_workspace_cwd_is_used_for_planner_session(tmp_path):
    async def run():
        plugin = FakePlugin()
        plugin.list_workspaces = lambda: asyncio.sleep(
            0, result=[{"id": "workspace-id", "cwd": str(tmp_path / "repo")}]
        )
        supervisor = Supervisor(
            tmp_path / "data", {"claude-sdk": cast("RunnerPlugin", plugin)}
        )
        await supervisor.start_planner_session(
            "item-cwd", tmp_path / "request.md", "workspace-id", config_file(tmp_path)
        )
        try:
            assert plugin.specs[0].cwd == str((tmp_path / "repo").resolve())
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_exhausted_fallback_chain_raises_last_limit_error(tmp_path):
    async def run():
        primary = FakePlugin([RuntimeError("You've hit your usage limit")])
        fallback = FakePlugin([RuntimeError("second: hit your usage limit")])
        supervisor = Supervisor(
            tmp_path / "data",
            {
                "claude-sdk": cast("RunnerPlugin", primary),
                "opencode-http": cast("RunnerPlugin", fallback),
            },
        )
        with pytest.raises(RuntimeError, match="second: hit your usage limit"):
            await supervisor.start_planner_session(
                "item-3", tmp_path / "request.md", "workspace", config_file(tmp_path)
            )
        try:
            assert len(primary.specs) == len(fallback.specs) == 1
        finally:
            await supervisor.shutdown()

    asyncio.run(run())


def test_paseo_partial_start_is_stopped_before_fallback(tmp_path):
    async def run():
        plugin = PaseoPlugin(tmp_path / "paseo.sock", "ws://unused")
        operations = []

        async def respond(reader, writer):
            while line := await reader.readline():
                request = json.loads(line)
                operations.append(request)
                if request["op"] == "start":
                    response = {
                        "id": request["id"],
                        "error": "You've hit your usage limit",
                        "session_id": "partial-remote",
                    }
                elif request["op"] == "list_workspaces":
                    response = {"id": request["id"], "workspaces": []}
                else:
                    response = {"id": request["id"]}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()

        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", server.sockets[0].getsockname()[1]
        )
        plugin._writer = writer
        plugin._ready.set()
        plugin._reader_task = asyncio.create_task(plugin._read_messages(reader, writer))
        plugin._ensure_started = lambda: asyncio.sleep(0)
        fallback = FakePlugin()
        supervisor = Supervisor(
            tmp_path / "data",
            {"claude-sdk": plugin, "opencode-http": cast("RunnerPlugin", fallback)},
        )
        try:
            session = await supervisor.start_planner_session(
                "item-partial",
                tmp_path / "request.md",
                "workspace",
                config_file(tmp_path),
            )
            assert session.provider == "opencode-http"
            assert [request["op"] for request in operations] == [
                "list_workspaces",
                "start",
                "stop",
            ]
            assert operations[-1]["session_id"] == "partial-remote"
        finally:
            await supervisor.shutdown()
            writer.close()
            await writer.wait_closed()
            server.close()
            await server.wait_closed()
            await plugin._disconnect()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"error": {"type": "usage_limit_exceeded"}}, True),
        ({"code": "rate_limit_exceeded"}, False),
        ("You've hit your usage limit", True),
        ("usage limit reached", False),
        ("rate limit exceeded", False),
        ({"error": {"message": "usage limit reached"}}, False),
        ("authentication failed", False),
    ],
)
def test_provider_limit_error_classifier(error, expected):
    assert is_provider_limit_error(error) is expected
