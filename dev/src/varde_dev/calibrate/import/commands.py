"""Lazy CLI shim for pair import."""

from collections.abc import Sequence

from varde_dev.calibrate.store.commands import main as store_main


def main(argv: Sequence[str] | None = None) -> int:
    return store_main("import", argv)
