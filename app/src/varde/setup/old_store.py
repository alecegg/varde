"""Guard setup commands against unmigrated legacy stores."""

from __future__ import annotations

import os
from pathlib import Path

from varde_core.paths import varde_config_dir

MIGRATION_MARKER = ".varde-migration-complete"


class SetupError(Exception):
    """A setup command cannot continue until the user resolves its state."""

    exit_code = 1


def _legacy_stores(home: Path, xdg_config_home: Path) -> tuple[tuple[Path, Path], ...]:
    config_dir = varde_config_dir()
    return (
        (home / ".config" / "varde-code", config_dir / "code"),
        (xdg_config_home / "tool-output-zone", config_dir / "toz"),
    )


def check_old_store() -> None:
    """Raise a setup error if a legacy store still needs migration."""
    home = Path(os.environ.get("HOME") or Path.home())
    configured_xdg = os.environ.get("XDG_CONFIG_HOME")
    xdg_config_home = Path(configured_xdg) if configured_xdg else home / ".config"

    for legacy, migrated_store in _legacy_stores(home, xdg_config_home):
        marker = migrated_store / MIGRATION_MARKER
        if legacy.exists() and not marker.exists():
            raise SetupError(
                f"legacy store at {legacy} has not been migrated; "
                "run varde-rust's migrate first"
            )
