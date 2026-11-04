"""Configuration and default paths for the generic Node host."""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_runner.config import ConfigError

_ENGINE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclass(frozen=True)
class NodeHostSettings:
    node: str = "node"
    restart_max: int = 3
    restart_window_s: float = 300.0
    call_timeout_s: float = 60.0


def node_host_settings(text: str) -> NodeHostSettings:
    """Parse the standalone `[node_host]` table from runner.toml."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    values: Any = data.get("node_host", {})
    if not isinstance(values, dict):
        raise ConfigError("node_host must be a table")

    node = values.get("node", "node")
    if not isinstance(node, str) or not node.strip():
        raise ConfigError("node_host.node must be a non-empty executable path")

    restart_max = values.get("restart_max", 3)
    if (
        not isinstance(restart_max, int)
        or isinstance(restart_max, bool)
        or restart_max < 0
    ):
        raise ConfigError("node_host.restart_max must be an integer >= 0")

    restart_window_s = _positive_number(values, "restart_window_s", 300)
    call_timeout_s = _positive_number(values, "call_timeout_s", 60)
    return NodeHostSettings(node, restart_max, restart_window_s, call_timeout_s)


def _positive_number(values: dict[str, Any], key: str, default: int) -> float:
    value = values.get(key, default)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or not math.isfinite(value)
    ):
        raise ConfigError(f"node_host.{key} must be a positive number")
    return float(value)


def node_host_engine_path(
    engine: str, configured_path: str | Path | None = None
) -> Path:
    """Resolve an engine path from runner.toml or the runner package default."""
    if not _ENGINE_NAME.fullmatch(engine) or engine in {".", ".."}:
        raise ConfigError("engine name must be a simple path component")
    runner_root = Path(__file__).resolve().parents[2]
    path = (
        Path(configured_path).expanduser()
        if configured_path is not None
        else Path("node-host") / "engines" / engine / "index.mjs"
    )
    return (path if path.is_absolute() else runner_root / path).resolve()
