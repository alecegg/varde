"""Configuration and project store path resolution matching toz-core."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

MIGRATION_MARKER = ".varde-migration-complete"


def env_os(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    """Read a Varde-prefixed environment variable before its compatibility name."""
    values = os.environ if environ is None else environ
    canonical = values.get(f"VARDE_{name}")
    return canonical if canonical is not None else values.get(name)


def varde_config_dir(
    environ: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    values = os.environ if environ is None else environ
    configured = env_os("CONFIG_DIR", values)
    if configured:
        return Path(configured)
    xdg = env_os("XDG_CONFIG_HOME", values)
    if xdg:
        return Path(xdg) / "varde"
    user_home = home if home is not None else Path.home()
    return user_home / ".config" / "varde"


def data_dir(
    environ: dict[str, str] | None = None,
    home: Path | None = None,
    *,
    platform: str | None = None,
) -> Path | None:
    values = os.environ if environ is None else environ
    user_home = home if home is not None else Path.home()
    if (platform or sys.platform) == "darwin":
        return user_home / "Library" / "Application Support" if user_home else None
    xdg = env_os("XDG_DATA_HOME", values)
    if xdg and Path(xdg).is_absolute():
        return Path(xdg)
    return user_home / ".local" / "share" if user_home else None


def resolve_config_dir(
    explicit: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    if explicit is not None:
        return explicit
    values = os.environ if environ is None else environ
    user_home = home if home is not None else Path.home()
    base = Path(env_os("XDG_CONFIG_HOME", values) or user_home / ".config")
    config_root = varde_config_dir(values, user_home)
    current = config_root / "toz"
    if (current / MIGRATION_MARKER).exists():
        return current
    canonical = base / "varde-toz"
    legacy = base / "tool-output-zone"
    same_root = False
    with contextlib.suppress(OSError):
        same_root = canonical.resolve() == legacy.resolve()
    if legacy.exists() and not same_root:
        return legacy
    return canonical if canonical.exists() else current


def config_dir(
    environ: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    values = os.environ if environ is None else environ
    override = env_os("TOZ_CONFIG_DIR", values)
    if override is not None:
        return Path(override)
    return resolve_config_dir(environ=values, home=home)


def _expanded_store(value: str, project_root: Path, home: Path) -> Path | None:
    project_name = project_root.name
    expanded = value.replace("{project}", project_name)
    if expanded == "~" or expanded.startswith("~/"):
        expanded = str(home / expanded[2:]) if expanded.startswith("~/") else str(home)
    path = Path(expanded)
    return path if path.is_absolute() else None


def varde_toz_dir(
    project_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    import tomllib

    values = os.environ if environ is None else environ
    user_home = home if home is not None else Path.home()
    root = varde_config_dir(values, user_home)
    current = root / "config.toml"
    path = current if current.exists() else root / "paths.toml"
    try:
        with path.open("rb") as source:
            config = tomllib.load(source)
    except OSError, tomllib.TOMLDecodeError:
        return None
    canonical_root = project_root.resolve()
    projects = config.get("project", {})
    if isinstance(projects, dict):
        for key, entry in projects.items():
            try:
                matches = Path(key).resolve() == canonical_root
            except OSError:
                matches = False
            if (
                matches
                and isinstance(entry, dict)
                and isinstance(entry.get("toz"), str)
            ):
                return _expanded_store(entry["toz"], project_root, user_home)
    default = config.get("default", {})
    raw = default.get("toz") if isinstance(default, dict) else None
    return (
        _expanded_store(raw, project_root, user_home) if isinstance(raw, str) else None
    )


class ConfigError(ValueError):
    """Invalid or unsupported toz configuration."""


def config_int(section: Mapping[str, object], key: str, default: int) -> int:
    """Convert a configured value to int, preserving int() runtime behavior."""
    return int(cast("Any", section.get(key, default)))


def load_config(path: Path | None = None) -> dict[str, object]:
    import tomllib

    config_path = path or config_dir() / "config.toml"
    try:
        with config_path.open("rb") as source:
            config = tomllib.load(source)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"parsing {config_path}: {exc}") from exc
    if "sandbox" in config:
        sandbox = config["sandbox"]
        if not isinstance(sandbox, dict):
            raise ConfigError("sandbox must be a table")
        enabled = sandbox.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError("sandbox.enabled must be a boolean")
        if enabled:
            raise ConfigError(
                "[sandbox] is enabled but OS sandboxing is not supported by varde-toz"
            )
    return config
