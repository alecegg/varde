"""Varde module entry point for the tool output zone."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from varde_core.io import Io

HELP_DIR = Path(__file__).with_name("help")
_HELP_ALIASES = {
    "profiles list": "profile list",
    "profiles test": "profile test",
    "setup doctor": "doctor",
    "setup migrate-metadata": "migrate-metadata",
    "setup profiles list": "profile list",
    "setup profiles test": "profile test",
}


@dataclass(frozen=True)
class Module:
    """Expose toz commands through the shared Varde module contract."""

    name: str = "toz"

    def run(self, argv: list[str], io: Io) -> int:
        """Run a toz command and return its CLI status."""
        from .cli import main

        if argv and (argv[0] == "varde" or argv[0].startswith("varde ")):
            argv = argv[1:]
        return main(argv)

    def help(self, path: str) -> str:
        """Return the committed help snapshot for a command route."""
        route = " ".join(path.split())
        route = _HELP_ALIASES.get(route, route)
        snapshot = HELP_DIR / f"{route.replace(' ', '_')}.txt"
        return snapshot.read_text() if snapshot.is_file() else ""


def register() -> Module:
    """Register the toz module with the application router."""
    return Module()
