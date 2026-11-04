"""Thin CLI shim delegating rank commands to the ranking package."""

from collections.abc import Sequence

from varde_dev.calibrate.ranking.commands import main as ranking_main


def main(argv: Sequence[str] | None = None) -> int:
    return ranking_main(argv)
