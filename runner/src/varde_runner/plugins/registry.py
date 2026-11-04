"""Harness keyed registry for runner plugins."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from typing import Any, cast

from varde_runner.config import Model
from varde_runner.plugins import RunnerCapabilities, SessionSettings
from varde_runner.protocol import RunnerPlugin


class UnknownHarness(KeyError):
    """Raised when no plugin is registered for a harness."""


class _MappingPlugin:
    """Adapt legacy provider mappings to the current plugin contract."""

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self.capabilities = plugin.capabilities

    def __getattr__(self, name: str) -> Any:
        return getattr(self._plugin, name)

    def session_settings(self, model: Model) -> SessionSettings:
        hook = getattr(self._plugin, "session_settings", None)
        if callable(hook):
            return cast("SessionSettings", hook(model))
        return SessionSettings(model.model, model.reasoning_effort, model.mode)


class PluginRegistry:
    def __init__(self, known_harnesses: Iterable[str] = ()) -> None:
        self._plugins: dict[str, Any] = {}
        self._provider_keys: dict[str, str] = {}
        self._providers: dict[str, Any] = {}
        self._known_harnesses = set(known_harnesses)
        self._config_tables: set[str] = set()

    def register_config_table(self, table: str) -> None:
        self._config_tables.add(table)

    def config_tables(self) -> frozenset[str]:
        return frozenset(self._config_tables)

    def register(
        self, harness: str, plugin: Any, provider_key: str | None = None
    ) -> None:
        key = provider_key or harness
        existing = self._providers.get(key)
        if existing is not None and existing is not plugin:
            raise ValueError(f"provider key is already registered: {key}")
        self._plugins[harness] = plugin
        self._provider_keys[harness] = key
        self._providers[key] = plugin
        self._known_harnesses.add(harness)
        config_table = getattr(plugin, "config_table", None)
        if isinstance(config_table, str):
            self.register_config_table(config_table)

    def plugin_for(self, harness: str) -> RunnerPlugin:
        try:
            return cast("RunnerPlugin", self._plugins[harness])
        except KeyError as exc:
            raise UnknownHarness(harness) from exc

    def plugin_for_key(self, key: str) -> RunnerPlugin | None:
        plugin = self._providers.get(key)
        return cast("RunnerPlugin", plugin) if plugin is not None else None

    def provider_key(self, harness: str) -> str:
        self.plugin_for(harness)
        return self._provider_keys[harness]

    def harnesses(self) -> frozenset[str]:
        return frozenset(self._plugins)

    def known_harnesses(self) -> frozenset[str]:
        return frozenset(self._known_harnesses)

    def config_choices(self, harness: str) -> dict[str, list[str]]:
        plugin = self.plugin_for(harness)
        get_choices = getattr(plugin, "config_choices", None)
        supplied = get_choices(harness) if callable(get_choices) else {}
        if not isinstance(supplied, dict):
            supplied = {}
        return {
            field: _string_choices(supplied.get(field))
            for field in ("harnesses", "models", "reasoning_efforts", "modes")
        }

    def capabilities(self, harness: str) -> RunnerCapabilities:
        return self.plugin_for(harness).capabilities

    async def list_workspaces(self, harness: str) -> list[dict[str, Any]]:
        plugin = self.plugin_for(harness)
        method = getattr(plugin, "list_workspaces", None)
        if not callable(method):
            return []
        result = method()
        workspaces = await result if inspect.isawaitable(result) else result
        return workspaces if isinstance(workspaces, list) else []

    def plugins(self) -> tuple[RunnerPlugin, ...]:
        unique: list[RunnerPlugin] = []
        seen: set[int] = set()
        for plugin in self._plugins.values():
            if id(plugin) in seen:
                continue
            seen.add(id(plugin))
            unique.append(plugin)
        return tuple(unique)

    @classmethod
    def from_mapping(
        cls,
        plugins: Mapping[str, Any],
        *,
        harness_by_key: Mapping[str, str] | None = None,
        known_harnesses: Iterable[str] = (),
    ) -> PluginRegistry:
        registry = cls(known_harnesses)
        adapters: dict[int, _MappingPlugin] = {}
        for key, plugin in plugins.items():
            harness = (harness_by_key or {}).get(key)
            if harness is None:
                resolver = getattr(plugin, "harness_for_provider", None)
                candidate = resolver(key) if callable(resolver) else key
                harness = candidate if isinstance(candidate, str) else key
                if harness == key and key not in registry.known_harnesses():
                    aliases = [
                        known
                        for known in registry.known_harnesses()
                        if known.startswith(f"{key}-")
                    ]
                    if len(aliases) == 1:
                        harness = aliases[0]
            adapter = adapters.setdefault(id(plugin), _MappingPlugin(plugin))
            registry.register(harness, adapter, provider_key=key)
        return registry


def _string_choices(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str)))
