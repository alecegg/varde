"""Pure byte-budget fitting for context_pack sections."""

from __future__ import annotations


def fit_sections(costs: dict[str, list[int]], budget: int) -> dict[str, int]:
    """Return how many leading items of each section fit in `budget` bytes.

    Items are ranked best first, so the tail of the currently largest section
    is dropped until the total fits.
    """
    kept = {name: len(items) for name, items in costs.items()}
    totals = {name: sum(items) for name, items in costs.items()}
    while sum(totals.values()) > budget:
        name = max((n for n in kept if kept[n]), key=lambda n: totals[n], default=None)
        if name is None:
            break
        kept[name] -= 1
        totals[name] -= costs[name][kept[name]]
    return kept
