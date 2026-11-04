from __future__ import annotations

import asyncio

import pytest
from varde_runner.plugins import RunnerCapabilities
from varde_runner.plugins.registry import PluginRegistry, UnknownHarness


class FakePlugin:
    capabilities = RunnerCapabilities(interrupt=True, respond=True)


def test_registry_lookup_and_capabilities() -> None:
    plugin = FakePlugin()
    registry = PluginRegistry()
    registry.register("fake-harness", plugin)  # type: ignore[arg-type]

    assert registry.plugin_for("fake-harness") is plugin
    assert registry.harnesses() == frozenset({"fake-harness"})
    assert registry.capabilities("fake-harness").interrupt
    assert registry.capabilities("fake-harness").respond


def test_registry_rejects_unknown_harness() -> None:
    with pytest.raises(UnknownHarness):
        PluginRegistry().plugin_for("missing")


def test_registry_from_mapping_keeps_provider_mapping_compatibility() -> None:
    plugin = FakePlugin()
    registry = PluginRegistry.from_mapping({"codex": plugin})  # type: ignore[dict-item]

    assert registry.plugin_for("codex").capabilities is plugin.capabilities


def test_registry_workspace_lookup_uses_requested_harness() -> None:
    class WorkspacePlugin(FakePlugin):
        async def list_workspaces(self):
            return [{"id": "workspace"}]

    registry = PluginRegistry()
    registry.register("workspace-harness", WorkspacePlugin())  # type: ignore[arg-type]

    assert asyncio.run(registry.list_workspaces("workspace-harness")) == [
        {"id": "workspace"}
    ]


def test_registry_workspace_lookup_returns_empty_without_capability() -> None:
    registry = PluginRegistry()
    registry.register("bare-harness", FakePlugin())  # type: ignore[arg-type]

    assert asyncio.run(registry.list_workspaces("bare-harness")) == []
