"""Thin shim to the panel command implementation."""

from collections.abc import Sequence

from varde_dev.calibrate.panel.commands import main as panel_main


def main(argv: Sequence[str] | None = None) -> int:
    return panel_main(argv)
