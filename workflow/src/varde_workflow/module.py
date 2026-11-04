"""Varde workflow plugin entry point."""

from __future__ import annotations

from dataclasses import dataclass

from varde_core.io import Io


@dataclass(frozen=True)
class WorkflowModule:
    name: str = "workflow"

    def run(self, argv: list[str], io: Io | None = None) -> int:
        from varde_workflow.cli import run

        return run(argv, io)

    def help(self, path: str = "") -> str:
        from varde_workflow.cli import help_text

        return help_text(path)


def register() -> WorkflowModule:
    return WorkflowModule()
