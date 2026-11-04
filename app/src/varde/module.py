"""App entry point for commands hosted directly by the CLI package."""

from dataclasses import dataclass

from varde_core.io import Io


@dataclass(frozen=True)
class AppModule:
    name: str = "app"

    def run(self, argv: list[str], io: Io) -> int:
        """App-level commands are dispatched by the CLI itself."""
        return 2

    def help(self, path: str) -> str:
        """Return app-level help text."""
        return "Usage: varde <COMMAND>\n"


def register():
    """Return this module implementation."""
    return AppModule()
