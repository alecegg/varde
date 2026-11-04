"""Command dispatch for the design module."""

from __future__ import annotations

from .cli import help_text, run


class _DesignModule:
    name = "design"

    def run(self, argv: list[str], io: object | None = None) -> int:
        return run(argv, io)

    def help(self, path: str = "") -> str:
        return help_text(path)


def register() -> _DesignModule:
    """Return the module interface used by the app entry point."""
    return _DesignModule()
