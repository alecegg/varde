"""Resolve configurable session locations for daily reviews."""

from __future__ import annotations

import os
import re
import stat
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HARNESSES = ("codex", "claude", "opencode", "pi")
LocationCheck = Callable[[Path], bool | tuple[str, str]]


@dataclass(frozen=True)
class Location:
    harness: str
    path: Path
    origin: str
    status: str
    reason: str
    ignored_paths: tuple[Path, ...] = ()


def _expand_home(value: str, env: dict[str, str]) -> str:
    if value == "~":
        return env.get("HOME", value)
    if value.startswith("~/") and env.get("HOME"):
        return str(Path(env["HOME"]) / value[2:])
    return value


def _expand_vars(value: str, env: dict[str, str]) -> str:
    return re.sub(
        r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
        lambda match: env.get(match.group(1) or match.group(2), match.group(0)),
        value,
    )


def _expand(value: str, env: dict[str, str]) -> Path:
    return Path(_expand_vars(_expand_home(value, env), env))


def _validate_roots(section: Any, harness: str) -> None:
    if not isinstance(section, dict):
        raise TypeError(f"invalid sources config: [{harness}] must be a table")
    unknown = set(section) - {"roots", "defaults"}
    if unknown:
        raise ValueError(
            f"invalid sources config: unknown key [{harness}].{min(unknown)}"
        )
    roots = section.get("roots", [])
    if not isinstance(roots, list) or not all(
        isinstance(root, str) and root for root in roots
    ):
        raise ValueError(
            f"invalid sources config: [{harness}].roots must be an array of paths"
        )


def _validate_defaults(section: dict[str, Any], harness: str) -> None:
    if "defaults" in section and not isinstance(section["defaults"], bool):
        raise ValueError(
            f"invalid sources config: [{harness}].defaults must be a boolean"
        )


def _validate_ignore(section: Any) -> list[str]:
    if not isinstance(section, dict):
        raise TypeError("invalid sources config: [ignore] must be a table")
    unknown = set(section) - {"paths"}
    if unknown:
        raise ValueError(f"invalid sources config: unknown key [ignore].{min(unknown)}")
    paths = section.get("paths", [])
    if not isinstance(paths, list) or not all(
        isinstance(path, str) and path for path in paths
    ):
        raise ValueError(
            "invalid sources config: [ignore].paths must be an array of paths"
        )
    return paths


def _validate(config: dict[str, Any]) -> dict[str, list[str]]:
    unknown = set(config) - {*HARNESSES, "ignore"}
    if unknown:
        raise ValueError(f"invalid sources config: unknown table {min(unknown)!r}")
    for harness in HARNESSES:
        section = config.get(harness, {})
        _validate_roots(section, harness)
        _validate_defaults(section, harness)
    return {"ignore": _validate_ignore(config.get("ignore", {}))}


def _opencode_root(env: dict[str, str]) -> Path:
    if env.get("OPENCODE_DB"):
        return Path(env["OPENCODE_DB"]).parent
    home = Path(env.get("HOME", str(Path.home())))
    return Path(env.get("XDG_DATA_HOME", str(home / ".local/share"))) / "opencode"


def _defaults(env: dict[str, str]) -> dict[str, Path]:
    home = Path(env.get("HOME", str(Path.home())))
    return {
        "codex": Path(env.get("CODEX_HOME", str(home / ".codex"))),
        "claude": Path(env.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
        / "projects",
        "opencode": _opencode_root(env),
        "pi": Path(
            env.get("PI_CODING_AGENT_SESSION_DIR", str(home / ".pi/agent/sessions"))
        ),
    }


def is_ignored(path: str | Path, ignore_paths: Iterable[str | Path]) -> bool:
    """Return whether path equals or is below an ignored path prefix."""
    candidate = Path(path)
    return any(
        candidate == ignored or ignored in candidate.parents
        for ignored in (Path(item) for item in ignore_paths)
    )


def resolve_locations(
    config: dict[str, Any], env: dict[str, str], exists: LocationCheck
) -> list[Location]:
    """Resolve defaults and configured roots; duplicates remain visible."""
    validated = _validate(config)
    ignored = tuple(_expand(path, env) for path in validated["ignore"])
    defaults = _defaults(env)
    locations = []
    for harness in HARNESSES:
        section = config.get(harness, {})
        roots = []
        if section.get("defaults", True):
            roots.append((_expand(str(defaults[harness]), env), "default"))
        roots.extend(
            (_expand(root, env), "config") for root in section.get("roots", [])
        )
        for root_path, origin in roots:
            result = exists(root_path)
            if isinstance(result, tuple):
                status, reason = result
            else:
                status, reason = (
                    ("ok", "") if result else ("missing", "location does not exist")
                )
            locations.append(
                Location(harness, root_path, origin, status, reason, ignored)
            )
    return locations


def _permission_bits_allow_read(path: Path, mode: int) -> bool:
    if path.is_dir():
        return bool(mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)) and bool(
            mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        )
    return bool(mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH))


def _check_readable(path: Path) -> tuple[str, str]:
    try:
        info = path.stat()
    except FileNotFoundError:
        return "missing", "location does not exist"
    except OSError as exc:
        return "unreadable", str(exc) or "cannot inspect location"
    if not _permission_bits_allow_read(path, info.st_mode) or not os.access(
        path, os.R_OK
    ):
        return "unreadable", "permission denied"
    return "ok", ""


def load_locations(
    path: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
    exists: LocationCheck | None = None,
) -> list[Location]:
    """Load the optional per-user TOML config and resolve its locations."""
    environment = dict(os.environ if env is None else env)
    config_path = (
        Path(path)
        if path is not None
        else Path(environment.get("HOME", str(Path.home())))
        / ".config/varde/learn/sources.toml"
    )
    try:
        with config_path.open("rb") as source:
            config = tomllib.load(source)
    except FileNotFoundError:
        config = {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid sources config {config_path}: {exc}") from exc
    checker = exists or _check_readable
    try:
        return resolve_locations(config, environment, checker)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{exc} ({config_path})") from exc
