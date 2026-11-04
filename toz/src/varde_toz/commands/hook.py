"""Hook command adapter, kept lazy so ordinary CLI imports do not load hook code."""

from varde_toz.hook import main as run_hook


def main(argv: list[str]) -> int:
    return run_hook(argv)
