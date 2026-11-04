"""Thin report command shim."""

from collections.abc import Sequence

from varde_dev.calibrate.reports.commands import main as reports_main


def main(argv: Sequence[str] | None = None) -> int:
    return reports_main("report", argv)
