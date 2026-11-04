"""Validated, immutable snapshots of runner role configuration."""

from __future__ import annotations

import fnmatch
import math
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

KNOWN_HARNESSES = {"codex-app-server", "pi", "claude-sdk"}
MAIL_SOAK_SCHEDULE_ENV = "VARDE_MAIL_SOAK_TIME"
KNOWN_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
PI_REASONING_EFFORTS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
KNOWN_MODES = {
    "auto",
    "read-only",
    "workspace-write",
    "full-access",
    "danger-full-access",
}
ROLE_NAMES = (
    "orchestrator",
    "planner",
    "builder",
    "explorer",
    "reviewer",
    "judge",
    "guard",
    "manager-bot",
)
OVERRIDE_KEYS = frozenset({"harness", "model", "reasoning_effort", "mode", "fallback"})


class ConfigError(ValueError):
    """Invalid runner.toml content."""


def _startup_timeout_setting(data: Mapping[str, Any]) -> float:
    value = data.get("startup_timeout_s", 30)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigError("startup_timeout_s must be a positive number")
    return float(value)


def _startup_kill_timeout_setting(data: Mapping[str, Any], warn_s: float) -> float:
    if "startup_kill_timeout_s" not in data:
        return max(300.0, warn_s)
    value = data["startup_kill_timeout_s"]
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        or (value != 0 and value < warn_s)
    ):
        raise ConfigError(
            "startup_kill_timeout_s must be 0 or at least startup_timeout_s"
        )
    return float(value)


def _startup_timeout_settings(data: Mapping[str, Any]) -> tuple[float, float]:
    warn_s = _startup_timeout_setting(data)
    return warn_s, _startup_kill_timeout_setting(data, warn_s)


def _stall_after_setting(data: Mapping[str, Any]) -> float:
    value = data.get("stall_after_s", 600)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigError("stall_after_s must be a positive number")
    return float(value)


def _idle_process_timeout_setting(data: Mapping[str, Any]) -> int:
    runner = data.get("runner", {})
    if not isinstance(runner, dict):
        raise ConfigError("runner must be a table")
    value = runner.get("idle_process_timeout_s", 600)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError("idle_process_timeout_s must be a non-negative integer")
    return value


def _max_live_instances_setting(data: Mapping[str, Any]) -> int:
    limits = data.get("limits", {})
    if not isinstance(limits, dict):
        raise ConfigError("limits must be a table")
    value = limits.get("max_live_instances", 8)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError("limits.max_live_instances must be an integer >= 1")
    return value


def _configured_user_pairing(data: Mapping[str, Any]) -> bool:
    runner = data.get("runner", {})
    if not isinstance(runner, dict) or not isinstance(
        runner.get("require_user_pairing", False), bool
    ):
        raise ConfigError("runner.require_user_pairing must be a boolean")
    return runner.get("require_user_pairing", False)


def configured_user_pairing(text: str) -> bool:
    """Read the optional user-only route gate without resolving harness roles."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    return _configured_user_pairing(data)


def claude_cli_enabled(text: str) -> bool:
    """Return whether the optional raw Claude CLI adapter is enabled."""
    try:
        value = tomllib.loads(text).get("claude_cli", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("enabled", False), bool):
        raise ConfigError("claude_cli.enabled must be a boolean")
    return value.get("enabled", False)


def claude_sdk_settings(text: str) -> tuple[bool, float]:
    """Return native SDK enablement and stream silence threshold."""
    try:
        value = tomllib.loads(text).get("claude_sdk", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("claude_sdk must be a table")
    enabled = value.get("enabled", True)
    timeout = value.get("stream_idle_timeout_s", 300)
    if not isinstance(enabled, bool):
        raise ConfigError("claude_sdk.enabled must be a boolean")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
        or not math.isfinite(timeout)
    ):
        raise ConfigError("claude_sdk.stream_idle_timeout_s must be positive")
    return enabled, float(timeout)


def configured_allowed_hosts(text: str) -> tuple[str, ...]:
    """Return the top-level `allowed_hosts` list from runner.toml text."""
    try:
        value = tomllib.loads(text).get("allowed_hosts", [])
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError("allowed_hosts must be a list of strings")
    return tuple(value)


def _codex_app_server_settings(value: Any) -> tuple[bool, str | None]:
    if not isinstance(value, dict):
        raise ConfigError("codex_app_server must be a table")
    enabled, binary = value.get("enabled", True), value.get("binary")
    if not isinstance(enabled, bool):
        raise ConfigError("codex_app_server.enabled must be a boolean")
    if binary is not None and (not isinstance(binary, str) or not binary.strip()):
        raise ConfigError("codex_app_server.binary must be a non-empty path")
    return enabled, binary


def codex_app_server_settings(text: str) -> tuple[bool, str | None]:
    """Return native Codex enablement and optional executable path."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    return _codex_app_server_settings(data.get("codex_app_server", {}))


def pi_rpc_enabled(text: str) -> bool:
    """Return whether the optional native Pi RPC adapter is enabled."""
    try:
        value = tomllib.loads(text).get("pi_rpc", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("enabled", True), bool):
        raise ConfigError("pi_rpc.enabled must be a boolean")
    return value.get("enabled", True)


@dataclass(frozen=True)
class PiDurableSettings:
    enabled: bool = False
    storage_dir: str = "pi-durable"
    provider: str | None = None
    model: str | None = None
    key_env: str | None = None
    stream_idle_timeout_s: float = 300.0


def pi_durable_settings(text: str) -> PiDurableSettings:
    """Parse the opt-in Pi Durable engine configuration."""
    try:
        value = tomllib.loads(text).get("pi_durable", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("pi_durable must be a table")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("pi_durable.enabled must be a boolean")
    storage_dir = value.get("storage_dir", "pi-durable")
    if not isinstance(storage_dir, str) or not storage_dir.strip():
        raise ConfigError("pi_durable.storage_dir must be a non-empty path")
    provider, model, key_env = (
        value.get(name) for name in ("provider", "model", "key_env")
    )
    if enabled:
        if not isinstance(provider, str) or not provider.strip():
            raise ConfigError("pi_durable.provider is required when enabled")
        if not isinstance(model, str) or not model.strip() or "/" not in model:
            raise ConfigError("pi_durable.model must be provider-prefixed")
        if model.split("/", 1)[0] != provider:
            raise ConfigError("pi_durable.provider and model prefix must match")
        if not isinstance(key_env, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", key_env
        ):
            raise ConfigError("pi_durable.key_env must be an environment variable name")
    timeout = value.get("stream_idle_timeout_s", 300)
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ConfigError("pi_durable.stream_idle_timeout_s must be a positive number")
    return PiDurableSettings(
        enabled, storage_dir, provider, model, key_env, float(timeout)
    )


def opencode_http_settings(text: str) -> tuple[bool, str | None]:
    """Return native OpenCode enablement and optional executable path."""
    try:
        value = tomllib.loads(text).get("opencode_http", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("opencode_http must be a table")
    enabled, binary = value.get("enabled", True), value.get("binary")
    if not isinstance(enabled, bool):
        raise ConfigError("opencode_http.enabled must be a boolean")
    if binary is not None and (not isinstance(binary, str) or not binary.strip()):
        raise ConfigError("opencode_http.binary must be a non-empty path")
    return enabled, binary


@dataclass(frozen=True)
class Model:
    harness: str
    model: str
    reasoning_effort: str
    mode: str


@dataclass(frozen=True)
class Role:
    harness: str
    model: str
    reasoning_effort: str
    mode: str
    fallback: tuple[Model, ...]
    enabled: bool = True


@dataclass(frozen=True)
class RoleConfig:
    roles: Mapping[str, Role]
    never_models: tuple[str, ...]
    max_no_progress_restarts: int = 3
    claude_cli_enabled: bool = False
    codex_app_server_enabled: bool = True
    codex_app_server_binary: str | None = None
    startup_timeout_s: float = 30.0
    startup_kill_timeout_s: float = 300.0
    stall_after_s: float = 600.0
    idle_process_timeout_s: int = 600
    max_live_instances: int = 8
    require_user_pairing: bool = False
    allow_fallback_only_on: tuple[str, ...] = ("provider_limit",)

    def resolve(self, name: str) -> Role:
        role = self.roles.get(name)
        if role is not None:
            return role
        if name in ROLE_NAMES:
            return default_config().roles[name]
        raise ConfigError(f"unknown role: {name}")

    def guard(self) -> Role | None:
        role = self.roles.get("guard")
        return role if role is not None and role.enabled else None


def config_dir() -> Path:
    """Return the directory containing runner configuration files."""
    configured = os.environ.get("VARDE_RUNNER_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".config" / "varde"


def config_path() -> Path:
    return config_dir() / "runner.toml"


def adapter_state_root() -> Path:
    """Return the root directory used for native adapter state."""
    configured = os.environ.get("VARDE_RUNNER_STATE_DIR")
    return Path(configured) if configured else Path.home() / ".local/share/varde-runner"


def _model(
    data: Any,
    label: str,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> Model:
    if not isinstance(data, dict):
        raise ConfigError(f"{label} must be a table")
    harness, model = data.get("harness"), data.get("model")
    effort, mode = data.get("reasoning_effort"), data.get("mode")
    if harness == "claude-cli" and harness not in known_harnesses:
        raise ConfigError(
            "claude-cli harness is disabled; set [claude_cli] enabled = true"
        )
    if not isinstance(harness, str) or harness not in known_harnesses:
        raise ConfigError(f"{label} has unknown harness: {harness!r}")
    if not isinstance(model, str) or not model.strip():
        raise ConfigError(f"{label} model must be non-empty")
    if any(
        fnmatch.fnmatchcase(model.casefold(), pattern.casefold())
        for pattern in never_models
    ):
        raise ConfigError(f"{label} uses prohibited model: {model}")
    if not isinstance(effort, str):
        raise ConfigError(f"{label} has unknown reasoning_effort: {effort!r}")
    if harness == "pi-rpc":
        if effort not in PI_REASONING_EFFORTS:
            accepted = ", ".join(PI_REASONING_EFFORTS)
            raise ConfigError(
                f"{label} Pi RPC reasoning_effort must be one of: {accepted}"
            )
    elif effort not in KNOWN_REASONING_EFFORTS:
        raise ConfigError(f"{label} has unknown reasoning_effort: {effort!r}")
    if not isinstance(mode, str) or mode not in KNOWN_MODES:
        raise ConfigError(f"{label} has unknown mode: {mode!r}")
    return Model(harness, model, effort, mode)


def _validate_native_codex_mode(model: Model | Role, label: str) -> None:
    supported = {"read-only", "workspace-write", "auto", "full-access"}
    if model.harness == "codex-app-server" and model.mode not in supported:
        raise ConfigError(
            f"{label} mode is not supported by native codex-app-server: {model.mode}"
        )


def _validate_native_opencode_mode(model: Model | Role, label: str) -> None:
    if model.harness == "opencode-http" and model.mode not in {
        "read-only",
        "workspace-write",
        "auto",
        "full-access",
    }:
        raise ConfigError(
            f"{label} mode is not supported by native opencode-http: {model.mode}"
        )


def _validate_native_pi_role(role: Role, label: str) -> None:
    for role_part in (role, *role.fallback):
        if role_part.harness != "pi-rpc":
            continue
        if not _is_pi_read_only(role_part.harness, role_part.mode):
            raise ConfigError(
                f"{label} uses pi-rpc mode {role_part.mode}, which requires "
                "approvals; Pi RPC has no approval flow. Use read-only or "
                "another harness."
            )
        if role_part.reasoning_effort not in PI_REASONING_EFFORTS:
            accepted = ", ".join(PI_REASONING_EFFORTS)
            raise ConfigError(
                f"{label} Pi RPC reasoning_effort must be one of: {accepted}"
            )


def _is_pi_read_only(harness: str, mode: str) -> bool:
    return harness == "pi-rpc" and mode == "read-only"


def _validate_pi_rpc_setting(data: dict[str, Any], enabled: bool) -> None:
    if enabled:
        return
    configured_harnesses = _configured_harnesses(data)
    if "pi-rpc" in configured_harnesses:
        raise ConfigError("pi-rpc harness is disabled; set [pi_rpc] enabled = true")


def _validate_pi_durable_setting(data: dict[str, Any], text: str) -> bool:
    enabled = pi_durable_settings(text).enabled
    if not enabled and "pi-durable" in _configured_harnesses(data):
        raise ConfigError(
            "pi-durable harness is disabled; set [pi_durable] enabled = true"
        )
    return enabled


def _optional_pi_harnesses(data: dict[str, Any], text: str) -> tuple[bool, bool]:
    rpc_enabled = pi_rpc_enabled(text)
    _validate_pi_rpc_setting(data, rpc_enabled)
    return rpc_enabled, _validate_pi_durable_setting(data, text)


def _validate_opencode_http_setting(data: dict[str, Any], text: str) -> bool:
    enabled, _ = opencode_http_settings(text)
    if not enabled and "opencode-http" in _configured_harnesses(data):
        raise ConfigError(
            "opencode-http harness is disabled; set [opencode_http] enabled = true"
        )
    return enabled


def _configured_harnesses(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {value["harness"]} if isinstance(value.get("harness"), str) else set()
        return found.union(*(_configured_harnesses(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_configured_harnesses(item) for item in value))
    return set()


def _enabled_harnesses(
    known: set[str] | frozenset[str],
    claude_cli: bool,
    pi_rpc: bool,
    opencode_http: bool = False,
    pi_durable: bool = False,
    claude_sdk: bool = False,
) -> set[str] | frozenset[str]:
    extra = ({"claude-cli"} if claude_cli else set()) | (
        {"pi-rpc"} if pi_rpc else set()
    )
    if opencode_http:
        extra.add("opencode-http")
    if pi_durable:
        extra.add("pi-durable")
    if claude_sdk:
        extra.add("claude-sdk")
    return {*known, *extra}


def _guard_role(
    raw: Any,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> Role:
    if not isinstance(raw, dict):
        raise ConfigError("roles.guard must be a table")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("roles.guard.enabled must be a boolean")
    primary = _model(
        {**raw, "mode": "read-only"}, "roles.guard", never_models, known_harnesses
    )
    fallback_data = raw.get("fallback", [])
    if not isinstance(fallback_data, list):
        raise ConfigError("roles.guard fallback must be an array")
    fallback = tuple(
        _model(item, "roles.guard.fallback", never_models, known_harnesses)
        for item in fallback_data
    )
    return Role(
        primary.harness,
        primary.model,
        primary.reasoning_effort,
        primary.mode,
        fallback,
        enabled,
    )


def _role(
    name: str,
    raw: Any,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> Role:
    if name == "guard":
        return _guard_role(raw, never_models, known_harnesses)
    primary = _model(raw, f"roles.{name}", never_models, known_harnesses)
    fallback_data = raw.get("fallback") if isinstance(raw, dict) else None
    if not isinstance(fallback_data, list) or not fallback_data:
        raise ConfigError(f"roles.{name} must have a non-empty fallback chain")
    fallback = tuple(
        _model(item, f"roles.{name}.fallback", never_models, known_harnesses)
        for item in fallback_data
    )
    return Role(
        primary.harness,
        primary.model,
        primary.reasoning_effort,
        primary.mode,
        fallback,
    )


TYPE_DEFINITIONS = {
    "standard": ("claude-sdk", "claude-sonnet-5-5", "medium"),
    "heavy": ("claude-sdk", "claude-sonnet-5-5", "high"),
    "light": ("codex-app-server", "gpt-6-luna", "medium"),
}
TYPE_FALLBACK = ("opencode-http", "opencode-go/deepseek-v4.1-flash", "high")
DEFAULT_ROLE_TYPES = {
    "orchestrator": "standard",
    "planner": "standard",
    "builder": "light",
    "explorer": "light",
    "reviewer": "standard",
    "judge": "standard",
    "guard": "light",
    "manager-bot": "standard",
}


def _type_role(
    type_name: str,
    type_data: Any,
    role_name: str,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> Role:
    if not isinstance(type_data, dict):
        raise ConfigError(f"types.{type_name} must be a table")
    if (
        "mode" in type_data
        and not _is_pi_read_only(
            type_data.get("harness", ""), type_data.get("mode", "")
        )
        and type_data.get("harness") not in {"pi-rpc", "opencode-http"}
    ):
        raise ConfigError(f"types.{type_name}.mode is not configurable")
    primary_data = {
        key: type_data.get(key) for key in ("harness", "model", "reasoning_effort")
    }
    role_mode = type_data.get(
        "mode", "read-only" if role_name == "guard" else "workspace-write"
    )
    primary_data["mode"] = role_mode
    primary = _model(primary_data, f"types.{type_name}", never_models, known_harnesses)
    raw_fallback = type_data.get("fallback", [])
    if not isinstance(raw_fallback, list):
        raise ConfigError(f"types.{type_name}.fallback must be an array")
    if role_name != "guard" and not raw_fallback:
        raise ConfigError(f"types.{type_name} must have a non-empty fallback chain")
    for item in raw_fallback:
        if (
            isinstance(item, dict)
            and "mode" in item
            and item.get("harness") not in {"pi-rpc", "opencode-http"}
        ):
            raise ConfigError(f"types.{type_name}.fallback mode is not configurable")
    fallback = tuple(
        _model(
            {
                **item,
                "mode": item.get("mode", "workspace-write"),
            }
            if isinstance(item, dict)
            else item,
            f"types.{type_name}.fallback",
            never_models,
            known_harnesses,
        )
        for item in raw_fallback
    )
    role = Role(
        primary.harness, primary.model, primary.reasoning_effort, role_mode, fallback
    )
    _validate_native_pi_role(role, f"types.{type_name}")
    _validate_native_opencode_mode(role, f"types.{type_name}")
    if role_name == "guard":
        return Role(
            primary.harness, primary.model, primary.reasoning_effort, role_mode, ()
        )
    return role


def _expected_roles(name: str) -> list[tuple[str, Role]]:
    mode = "read-only" if name == "guard" else "workspace-write"
    fallback = () if name == "guard" else (Model(*TYPE_FALLBACK, "workspace-write"),)
    return [
        (
            type_name,
            Role(harness, model, effort, mode, fallback),
        )
        for type_name, (harness, model, effort) in TYPE_DEFINITIONS.items()
    ]


def _role_diff(role: Role, expected: Role) -> list[str]:
    fields = ("harness", "model", "reasoning_effort", "mode", "fallback")
    return [
        f"{field} {getattr(role, field)!r} (expected {getattr(expected, field)!r})"
        for field in fields
        if getattr(role, field) != getattr(expected, field)
    ]


def legacy_type_name(name: str, role: Role) -> str | None:
    """Return the built-in type matched by a resolved legacy role."""
    return next(
        (
            type_name
            for type_name, expected in _expected_roles(name)
            if not _role_diff(role, expected)
        ),
        None,
    )


def _legacy_type(
    name: str,
    raw: Any,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> Role:
    if not isinstance(raw, dict):
        raise ConfigError(f"roles.{name} must be a table")
    if "type" in raw:
        raise ConfigError(f"roles.{name} uses type but no [types] table is defined")
    allowed = set(OVERRIDE_KEYS)
    if name in {"guard", "manager-bot"}:
        allowed.add("enabled")
    unknown = raw.keys() - allowed
    if unknown:
        raise ConfigError(
            f"roles.{name} has unknown keys: {', '.join(sorted(unknown))}"
        )
    enabled = raw.get("enabled", False) if name == "manager-bot" else True
    if name == "manager-bot" and not isinstance(enabled, bool):
        raise ConfigError("roles.manager-bot.enabled must be a boolean")
    role = _role(name, raw, never_models, known_harnesses)
    if name == "manager-bot":
        role = Role(
            role.harness,
            role.model,
            role.reasoning_effort,
            role.mode,
            role.fallback,
            enabled,
        )
    _validate_native_pi_role(role, f"roles.{name}")
    _validate_native_opencode_mode(role, f"roles.{name}")
    if legacy_type_name(name, role) is not None:
        return role
    expected_roles = _expected_roles(name)
    closest_name, closest = min(
        expected_roles, key=lambda item: len(_role_diff(role, item[1]))
    )
    raise ConfigError(
        f"roles.{name} does not match a built-in type; closest is {closest_name}: "
        f"{'; '.join(_role_diff(role, closest))}"
    )


def _validate_types(
    types_data: Any,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> dict[str, Any] | None:
    if types_data is None:
        return None
    if not isinstance(types_data, dict):
        raise ConfigError("types must be a table")
    for type_name, type_raw in types_data.items():
        if isinstance(type_raw, dict):
            if (
                "mode" in type_raw
                and not _is_pi_read_only(
                    type_raw.get("harness", ""), type_raw.get("mode", "")
                )
                and type_raw.get("harness") not in {"pi-rpc", "opencode-http"}
            ):
                raise ConfigError(f"types.{type_name}.mode is not configurable")
            configurable = OVERRIDE_KEYS - {"mode"}
            if type_raw.get("harness") in {"pi-rpc", "opencode-http"}:
                configurable = configurable | {"mode"}
            unknown = type_raw.keys() - configurable
            if unknown:
                raise ConfigError(
                    f"types.{type_name} has unknown keys: {', '.join(sorted(unknown))}"
                )
        _type_role(type_name, type_raw, "", never_models, known_harnesses)
    return types_data


def _default_types() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "harness": harness,
            "model": model,
            "reasoning_effort": effort,
            "fallback": [
                {
                    "harness": TYPE_FALLBACK[0],
                    "model": TYPE_FALLBACK[1],
                    "reasoning_effort": TYPE_FALLBACK[2],
                }
            ],
        }
        for name, (harness, model, effort) in TYPE_DEFINITIONS.items()
    }


def _configured_types(
    raw_types: Any,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> dict[str, Any] | None:
    if raw_types is None:
        return None
    if not isinstance(raw_types, dict):
        raise ConfigError("types must be a table")
    types_data = _default_types()
    types_data.update(raw_types)
    return _validate_types(types_data, never_models, known_harnesses)


def _configured_role(
    name: str,
    raw: Any,
    types_data: dict[str, Any] | None,
    never_models: tuple[str, ...],
    known_harnesses: set[str] | frozenset[str],
) -> Role:
    if types_data is None:
        role = _legacy_type(name, raw, never_models, known_harnesses)
        _validate_pi_durable_role(role, name)
        return role
    if not isinstance(raw, dict):
        raise ConfigError(f"roles.{name} must be a table")
    enabled_role = name in {"guard", "manager-bot"}
    allowed = {"type", "enabled"} if enabled_role else {"type"}
    unknown = raw.keys() - allowed - OVERRIDE_KEYS
    if unknown:
        raise ConfigError(
            f"roles.{name} has unknown keys: {', '.join(sorted(unknown))}"
        )
    overrides = OVERRIDE_KEYS & raw.keys()
    if overrides:
        raise ConfigError(
            f"roles.{name} cannot override type settings: "
            f"{', '.join(sorted(overrides))}"
        )
    type_name = raw.get("type")
    if not isinstance(type_name, str) or type_name not in types_data:
        raise ConfigError(f"roles.{name} has unknown type: {type_name!r}")
    enabled = raw.get("enabled", False) if enabled_role else True
    if enabled_role and not isinstance(enabled, bool):
        raise ConfigError(f"roles.{name}.enabled must be a boolean")
    role = _type_role(
        type_name, types_data[type_name], name, never_models, known_harnesses
    )
    _validate_pi_durable_role(role, name)
    if not enabled_role:
        return role
    return Role(
        role.harness,
        role.model,
        role.reasoning_effort,
        role.mode,
        () if name == "guard" else role.fallback,
        enabled,
    )


def _validate_pi_durable_role(role: Role, name: str) -> None:
    supported_roles = {"builder", "planner", "explorer", "reviewer"}
    for configured in (role, *role.fallback):
        if configured.harness != "pi-durable":
            continue
        if name not in supported_roles:
            raise ConfigError(f"roles.{name} is not supported by pi-durable")
        if configured.mode not in {"read-only", "workspace-write"}:
            raise ConfigError(
                f"roles.{name} pi-durable mode must be read-only or workspace-write"
            )


def parse_config(
    text: str, known_harnesses: set[str] | frozenset[str] = KNOWN_HARNESSES
) -> RoleConfig:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    if data.get("version") != 1:
        raise ConfigError("version must be 1")
    policy = data.get("policy")
    if not isinstance(policy, dict):
        raise ConfigError("policy table is required")
    never_models = policy.get("never_models")
    triggers = policy.get("allow_fallback_only_on")
    if not isinstance(never_models, list) or not all(
        isinstance(item, str) for item in never_models
    ):
        raise ConfigError("policy.never_models must be a list of strings")
    if (
        not isinstance(triggers, list)
        or not all(isinstance(item, str) for item in triggers)
        or len(set(triggers)) != len(triggers)
        or not set(triggers) <= {"provider_limit"}
    ):
        raise ConfigError("policy.allow_fallback_only_on supports provider_limit")
    if policy.get("create_paseo_projects") is not False:
        raise ConfigError("create_paseo_projects must be false")
    require_user_pairing = _configured_user_pairing(data)
    max_no_progress_restarts = data.get("max_no_progress_restarts", 3)
    if (
        not isinstance(max_no_progress_restarts, int)
        or isinstance(max_no_progress_restarts, bool)
        or max_no_progress_restarts < 1
    ):
        raise ConfigError("max_no_progress_restarts must be an integer >= 1")
    claude_cli = data.get("claude_cli", {})
    if not isinstance(claude_cli, dict) or not isinstance(
        claude_cli.get("enabled", False), bool
    ):
        raise ConfigError("claude_cli.enabled must be a boolean")
    claude_cli_enabled = claude_cli.get("enabled", False)
    codex_enabled, codex_binary = _codex_app_server_settings(
        data.get("codex_app_server", {})
    )
    pi_native_enabled, pi_durable_enabled = _optional_pi_harnesses(data, text)
    opencode_enabled = _validate_opencode_http_setting(data, text)
    raw_types = data.get("types")
    if (
        not claude_cli_enabled
        and isinstance(raw_types, dict)
        and any(
            isinstance(type_data, dict) and type_data.get("harness") == "claude-cli"
            for type_data in raw_types.values()
        )
    ):
        raise ConfigError(
            "claude-cli harness is disabled; set [claude_cli] enabled = true"
        )
    known_harnesses = _enabled_harnesses(
        known_harnesses,
        claude_cli_enabled,
        pi_native_enabled,
        opencode_enabled,
        pi_durable_enabled,
        claude_sdk_settings(text)[0],
    )
    roles_data = data.get("roles")
    if not isinstance(roles_data, dict):
        raise ConfigError("at least one role is required")
    types_data = _configured_types(
        data.get("types"), tuple(never_models), known_harnesses
    )
    roles: dict[str, Role] = {}
    for name, raw in roles_data.items():
        if name not in ROLE_NAMES:
            if name != "mailman":
                raise ConfigError(f"unknown role: {name}")
            continue
        raw_harness = raw.get("harness") if isinstance(raw, dict) else None
        if raw_harness == "claude-cli" and not claude_cli_enabled:
            raise ConfigError(
                "claude-cli harness is disabled; set [claude_cli] enabled = true"
            )
        roles[name] = _configured_role(
            name, raw, types_data, tuple(never_models), known_harnesses
        )
        if codex_enabled:
            role = roles[name]
            _validate_native_codex_mode(role, f"roles.{name}")
            for fallback in role.fallback:
                _validate_native_codex_mode(fallback, f"roles.{name}.fallback")
        _validate_native_pi_role(roles[name], f"roles.{name}")
        _validate_native_opencode_mode(roles[name], f"roles.{name}")
    if not roles:
        raise ConfigError("at least one role is required")
    return RoleConfig(
        MappingProxyType(roles),
        tuple(never_models),
        max_no_progress_restarts,
        claude_cli_enabled,
        codex_enabled,
        codex_binary,
        *_startup_timeout_settings(data),
        _stall_after_setting(data),
        _idle_process_timeout_setting(data),
        _max_live_instances_setting(data),
        require_user_pairing,
        tuple(triggers),
    )


_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\"'-]+?)\s*\]\]?\s*(#.*)?$")


def unknown_role_blocks(text: str) -> str:
    """Return the `[roles.<name>]` tables in `text` whose name is not a known role."""
    kept: list[str] = []
    keeping = False
    for line in text.splitlines():
        header = _TABLE_HEADER.match(line)
        if header:
            parts = [part.strip("\"'") for part in header.group(1).split(".")]
            keeping = (
                parts[0] == "roles" and len(parts) > 1 and parts[1] not in ROLE_NAMES
            )
        if keeping:
            kept.append(line)
    return "\n".join(kept).strip("\n")


def keep_unknown_roles(submitted: str, existing: str) -> str:
    """Append the existing file's unknown role tables to `submitted` unchanged."""
    blocks = unknown_role_blocks(existing)
    if not blocks or unknown_role_blocks(submitted):
        return submitted
    return submitted.rstrip("\n") + "\n\n" + blocks + "\n"


def load_config(
    path: Path | None = None,
    known_harnesses: set[str] | frozenset[str] = KNOWN_HARNESSES,
) -> RoleConfig:
    source = path or config_path()
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"cannot read {source}: {exc}") from exc
    return parse_config(text, known_harnesses)


def classify_limit_error(error: Any) -> bool:
    """Recognize explicit structured quota/usage exhaustion only."""
    if not isinstance(error, dict):
        return False
    details = error.get("error")
    if not isinstance(details, dict):
        return False
    code = str(details.get("type") or details.get("code") or "").casefold()
    return code in {
        "usage_limit_exceeded",
        "rate_limit_exceeded",
        "quota_exceeded",
    }


def default_config() -> RoleConfig:
    fallback = (Model(*TYPE_FALLBACK, "workspace-write"),)
    roles = {}
    for name in ROLE_NAMES:
        type_name = DEFAULT_ROLE_TYPES[name]
        if name == "guard":
            roles[name] = Role(
                "codex-app-server", "gpt-6-luna", "medium", "read-only", (), False
            )
            continue
        harness, model, effort = TYPE_DEFINITIONS[type_name]
        enabled = name != "manager-bot"
        roles[name] = Role(harness, model, effort, "workspace-write", fallback, enabled)
    return RoleConfig(
        MappingProxyType(roles),
        ("*-sol",),
        3,
        codex_app_server_enabled=True,
        max_live_instances=8,
    )


def default_toml() -> str:
    lines = [
        "version = 1",
        "max_no_progress_restarts = 3",
        "startup_timeout_s = 30",
        "startup_kill_timeout_s = 300",
        "stall_after_s = 600",
        "",
        "[runner]",
        "require_user_pairing = false",
        "idle_process_timeout_s = 600",
        "",
        "[limits]",
        "max_live_instances = 8",
        "",
        "[claude_cli]",
        "enabled = false",
        "",
        "[claude_sdk]",
        "enabled = true",
        "stream_idle_timeout_s = 300",
        "",
        "[codex_app_server]",
        "enabled = true",
        "",
        "[pi_rpc]",
        "enabled = true",
        "",
        "[pi_durable]",
        "enabled = false",
        'provider = "anthropic"',
        'model = "anthropic/claude-sonnet-4-5"',
        'key_env = "ANTHROPIC_API_KEY"',
        "",
        "[opencode_http]",
        "enabled = true",
        "",
    ]
    for type_name, (harness, model, effort) in TYPE_DEFINITIONS.items():
        lines.extend(
            (
                f"[types.{type_name}]",
                f'harness = "{harness}"',
                f'model = "{model}"',
                f'reasoning_effort = "{effort}"',
                "",
                f"[[types.{type_name}.fallback]]",
                f'harness = "{TYPE_FALLBACK[0]}"',
                f'model = "{TYPE_FALLBACK[1]}"',
                f'reasoning_effort = "{TYPE_FALLBACK[2]}"',
            )
        )
        lines.append("")
    for name in ROLE_NAMES:
        type_name = DEFAULT_ROLE_TYPES[name]
        lines.extend((f"[roles.{name}]", f'type = "{type_name}"'))
        if name in {"guard", "manager-bot"}:
            lines.append("enabled = false")
        lines.append("")
    lines.extend(
        (
            "[policy]",
            'never_models = ["*-sol"]',
            'allow_fallback_only_on = ["provider_limit"]',
            "create_paseo_projects = false",
            "",
        )
    )
    return "\n".join(lines)
