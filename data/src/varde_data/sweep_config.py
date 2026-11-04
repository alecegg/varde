"""Validated settings for learn's repository sweep."""

import tomllib
from pathlib import Path
from typing import Any


def _read_config(config_dir: Path) -> dict[str, Any]:
    config = config_dir / "sweep.toml"
    if not config.exists():
        return {}
    return tomllib.loads(config.read_text(encoding="utf-8"))


def load_sweep_repos(config_dir: Path) -> tuple[str, ...] | None:
    """Read configured repository paths, or None when the file is absent."""
    config = config_dir / "sweep.toml"
    if not config.exists():
        return None
    repos = _read_config(config_dir).get("repos", [])
    if not isinstance(repos, list) or any(not isinstance(item, str) for item in repos):
        raise ValueError("sweep config repos must be a list of paths")
    return tuple(repos)


def load_summary_config(config_dir: Path) -> tuple[bool, int]:
    """Read summary settings independently from repository path settings."""
    settings = _read_config(config_dir).get("summary", {})
    if not isinstance(settings, dict):
        raise TypeError("sweep summary config must be a table")
    enabled = settings.get("enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("sweep summary enabled must be true or false")
    cap = settings.get("token_cap", 2000)
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("sweep summary token_cap must be a positive integer")
    return enabled, cap
