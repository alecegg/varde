"""Command module registration for setup autosave, runner and serve."""

from dataclasses import dataclass
from pathlib import Path

from varde_core.io import Io


@dataclass(frozen=True)
class AutosaveModule:
    name: str = "autosave"

    def run(self, argv: list[str], io: Io) -> int:
        from .autosave import run

        return run(argv[1:], io)

    def help(self, path: str) -> str:
        snapshot = Path(__file__).parent / "help" / "autosave.txt"
        return snapshot.read_text(encoding="utf-8")


def register() -> AutosaveModule:
    """Return the autosave command module."""
    return AutosaveModule()


@dataclass(frozen=True)
class RunnerModule:
    name: str = "runner"

    def run(self, argv: list[str], io: Io) -> int:
        from .runner_switch import run

        return run(argv[1:], io)

    def help(self, path: str) -> str:
        snapshot = Path(__file__).parent / "help" / "runner.txt"
        return snapshot.read_text(encoding="utf-8")


def register_runner() -> RunnerModule:
    """Return the runner command module."""
    return RunnerModule()


@dataclass(frozen=True)
class ServeModule:
    name: str = "serve"

    def run(self, argv: list[str], io: Io) -> int:
        from .serve_cmd import run

        return run(argv[1:], io)

    def help(self, path: str) -> str:
        snapshot = Path(__file__).parent / "help" / "serve.txt"
        return snapshot.read_text(encoding="utf-8")


def register_serve() -> ServeModule:
    """Return the serve command module."""
    return ServeModule()
