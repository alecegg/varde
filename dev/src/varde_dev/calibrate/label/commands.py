"""Thin command boundary for the labeller implementation."""

from collections.abc import Sequence

from varde_dev.calibrate.labeller.commands import main as labeller_main


def main(argv: Sequence[str] | None = None) -> int:
    return labeller_main(argv)
