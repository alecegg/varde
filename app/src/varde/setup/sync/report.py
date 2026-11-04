"""Report and environment records shared with sync support steps."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from varde_core.paths import varde_config_dir

from varde.setup.hooks_install.json_hooks import stable_varde_path


@dataclass
class MigrateEnv:
    home: Path
    config_dir: Path
    xdg_config_home: Path | None
    path: str
    cargo_install_root: Path
    exe: Path
    toz_config_override: Path | None
    dry_run: bool = False

    @classmethod
    def current(cls, dry_run: bool = False) -> MigrateEnv:
        home = Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or ".")
        config_dir = varde_config_dir()
        xdg = os.environ.get("XDG_CONFIG_HOME") or None
        cargo_root = os.environ.get("CARGO_INSTALL_ROOT") or os.environ.get(
            "CARGO_HOME"
        )
        cargo = Path(cargo_root) if cargo_root else home / ".cargo"
        toz = os.environ.get("VARDE_TOZ_CONFIG_DIR") or os.environ.get("TOZ_CONFIG_DIR")
        return cls(
            home,
            config_dir,
            Path(xdg) if xdg else None,
            os.environ.get("PATH", ""),
            cargo,
            Path(stable_varde_path(home)),
            Path(toz) if toz else None,
            dry_run,
        )


@dataclass
class ReportEntry:
    path: Path
    reason: str
    command: str | None = None

    def __init__(self, path: str | Path, reason: str, command: str | None = None):
        self.path = Path(path)
        self.reason = reason
        self.command = command

    def with_command(self, command: str) -> ReportEntry:
        self.command = command
        return self

    def data(self) -> dict[str, str | None]:
        return {"path": str(self.path), "reason": self.reason, "command": self.command}


@dataclass
class Report:
    moved: list[ReportEntry] = field(default_factory=list)
    skipped: list[ReportEntry] = field(default_factory=list)
    unrewritable: list[ReportEntry] = field(default_factory=list)
    would: list[ReportEntry] = field(default_factory=list)

    def data(self) -> dict[str, list[dict[str, str | None]]]:
        return {
            name: [entry.data() for entry in getattr(self, name)]
            for name in ("moved", "skipped", "unrewritable", "would")
        }

    def __str__(self) -> str:
        lines = []
        for name in ("moved", "skipped", "unrewritable", "would"):
            for entry in getattr(self, name):
                suffix = f" ({entry.command})" if entry.command else ""
                lines.append(f"{name}: {entry.path}: {entry.reason}{suffix}")
        return "\n".join(lines) if lines else "no migration actions"
