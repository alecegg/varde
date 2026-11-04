"""Configuration helpers for native workspaces."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)


def configured_workspace_repos(text: str) -> tuple[Path, ...]:
    """Return valid configured checkout roots, warning and skipping bad entries."""
    try:
        value = tomllib.loads(text).get("workspaces", {}).get("repos", [])
    except (tomllib.TOMLDecodeError, AttributeError) as exc:
        logger.warning("Invalid workspaces configuration: %s", exc)
        return ()
    if not isinstance(value, list):
        logger.warning("workspaces.repos must be a list")
        return ()
    repos = []
    for item in value:
        if (
            not isinstance(item, str)
            or not Path(item).is_absolute()
            or not Path(item).is_dir()
        ):
            logger.warning("Ignoring invalid workspace repo %r", item)
            continue
        repos.append(Path(item).resolve())
    return tuple(dict.fromkeys(repos))
