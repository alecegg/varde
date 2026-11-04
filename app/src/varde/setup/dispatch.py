"""Dispatch setup commands that are not registered as command modules."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

_HELP = Path(__file__).parent / "help"
_HELP_PATHS = {
    ("setup", "sync"): "sync.txt",
    ("setup", "hooks", "install"): "hooks-install.txt",
    ("setup", "hooks", "remove"): "hooks-remove.txt",
}


def _write_help(path: tuple[str, ...]) -> int:
    text = (_HELP / _HELP_PATHS[path]).read_text(encoding="utf-8")
    if path == ("setup", "sync"):
        from .sync.skills import preset_names

        text = text.replace("{presets}", ", ".join(preset_names()))
    sys.stdout.write(text)
    return 0


def run_setup_route(args: Sequence[str]) -> int | None:
    """Run sync or hooks routes, returning ``None`` for other commands."""
    words = tuple(args)
    if words[:2] == ("setup", "sync"):
        if words[-1:] in (("--help",), ("-h",)):
            return _write_help(("setup", "sync"))
        from .sync.command import run

        return run(words[2:])
    if words[:3] in (("setup", "hooks", "install"), ("setup", "hooks", "remove")):
        path = words[:3]
        if words[-1:] in (("--help",), ("-h",)):
            return _write_help(path)
        from .hooks_install import run

        return run(words[2:])
    return None
