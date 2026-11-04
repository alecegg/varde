"""Dashboard plugin registry construction."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from varde_runner.config import (
    ConfigError,
    claude_cli_enabled,
    claude_sdk_settings,
    codex_app_server_settings,
    config_path,
    default_toml,
    opencode_http_settings,
    parse_config,
    pi_durable_settings,
    pi_rpc_enabled,
)
from varde_runner.guard_policy import validate_guard_role
from varde_runner.harness_map import HARNESS_TO_PASEO_PROVIDER
from varde_runner.plugins import RunnerCapabilities
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin
from varde_runner.plugins.claude_sdk.plugin import ClaudeSdkPlugin
from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin
from varde_runner.plugins.opencode_http.plugin import OpenCodeHttpPlugin
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.plugins.pi_durable.plugin import PiDurablePlugin
from varde_runner.plugins.pi_rpc.plugin import PiRpcPlugin
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import RunnerPlugin

NATIVE_HARNESSES = frozenset(
    {"claude-sdk", "codex-app-server", "pi-rpc", "opencode-http"}
)

MODEL_CATALOG_SCRIPT = """
import { createPaseoClient } from '@getpaseo/client';
const client = createPaseoClient({
  url: process.env.PASEO_URL || 'ws://127.0.0.1:6767/ws',
});
await client.connect();
try {
  const providers = ['codex', 'pi', 'claude'];
  const catalog = Object.fromEntries(await Promise.all(
    providers.map(async (provider) => [
      provider,
      await client.providers.listModels(provider),
    ])
  ));
  process.stdout.write(JSON.stringify(catalog));
} finally {
  await client.close();
}
"""


async def paseo_model_catalog() -> dict[str, Any]:
    sidecar_dir = Path(__file__).parents[3] / "sidecar"
    process = await asyncio.create_subprocess_exec(
        "node",
        "--input-type=module",
        "-e",
        MODEL_CATALOG_SCRIPT,
        cwd=sidecar_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("Paseo model list request timed out") from exc
    if process.returncode:
        detail = stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or "Paseo model list request failed")
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise TypeError("Paseo model list response must be an object")
    return value


class _PaseoRegistryPlugin:
    def __init__(self, plugin: PaseoPlugin) -> None:
        self._plugin = plugin
        self.capabilities = getattr(
            plugin, "capabilities", RunnerCapabilities(respond=True)
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._plugin, name)

    async def list_models(self) -> dict[str, Any]:
        return await paseo_model_catalog()


def build_registry(plugin: PaseoPlugin | None = None) -> PluginRegistry:
    adapter = plugin or PaseoPlugin.from_environment()
    registered = _PaseoRegistryPlugin(adapter)
    registry = PluginRegistry()
    settings_path = config_path()
    settings_text = (
        settings_path.read_text(encoding="utf-8")
        if settings_path.exists()
        else default_toml()
    )
    try:
        config = parse_config(settings_text)
    except ConfigError:
        codex_enabled, codex_binary = codex_app_server_settings(settings_text)
    else:
        codex_enabled = config.codex_app_server_enabled
        codex_binary = config.codex_app_server_binary
    pi_enabled = pi_rpc_enabled(settings_text)
    durable_settings = pi_durable_settings(settings_text)
    opencode_enabled, opencode_binary = opencode_http_settings(settings_text)
    sdk_enabled, _ = claude_sdk_settings(settings_text)
    for table in (
        ClaudeCliPlugin.config_table,
        ClaudeSdkPlugin.config_table,
        CodexAppServerPlugin.config_table,
        OpenCodeHttpPlugin.config_table,
        PiDurablePlugin.config_table,
        PiRpcPlugin.config_table,
    ):
        registry.register_config_table(table)
    for harness, provider in HARNESS_TO_PASEO_PROVIDER.items():
        if harness == "codex-app-server" and codex_enabled:
            continue
        if harness == "claude-sdk" and sdk_enabled:
            continue
        registry.register(
            harness, cast("RunnerPlugin", registered), provider_key=provider
        )
    if codex_enabled:
        registry.register(
            "codex-app-server",
            cast("RunnerPlugin", CodexAppServerPlugin(executable=codex_binary)),
        )
    if claude_cli_enabled(settings_text):
        registry.register("claude-cli", cast("RunnerPlugin", ClaudeCliPlugin()))
    if sdk_enabled:
        registry.register(
            "claude-sdk",
            cast("RunnerPlugin", ClaudeSdkPlugin(settings_text=settings_text)),
        )
    if pi_enabled:
        registry.register("pi-rpc", cast("RunnerPlugin", PiRpcPlugin()))
    if durable_settings.enabled:
        registry.register(
            "pi-durable",
            cast(
                "RunnerPlugin",
                PiDurablePlugin(durable_settings, config_text=settings_text),
            ),
        )
    if opencode_enabled:
        registry.register(
            "opencode-http",
            cast("RunnerPlugin", OpenCodeHttpPlugin(executable=opencode_binary)),
        )
    try:
        config = parse_config(settings_text, registry.known_harnesses())
    except ConfigError:
        pass
    else:
        guard = config.roles.get("guard")
        if guard is not None:
            validate_guard_role(guard, registry)
    return registry
