"""Deterministic margin-maximizing search over strengths scored by the real scorer.

Component debts are nonlinear in the strengths, so a candidate is judged by
re-scoring at that candidate (supplied as `worst_margin`), never by scaling
vectors extracted at another calibration.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..fixedpoint import MICRO

GRID_STEP = 50_000
COARSE_STRIDE = 4

# Contract: return the exact smallest margin when it is >= floor; otherwise any
# value below floor (callers may stop scoring early).
WorstMargin = Callable[[Mapping[str, int], int], int]


@dataclass(frozen=True)
class ExactFit:
    strengths: dict[str, int]
    worst: int


def grid_points(low: int, high: int, step: int = GRID_STEP) -> tuple[int, ...]:
    """Multiples of step in [low, high], so a refit on the same grid agrees."""
    first = -(-low // step) * step
    return tuple(range(first, high + 1, step))


def deviation(chosen: Sequence[int], start: Sequence[int]) -> int:
    """Relative distance from the starting strengths, used only to break ties."""
    return sum(
        abs(value - ref) * MICRO // max(1, ref)
        for value, ref in zip(chosen, start, strict=True)
    )


def fit_exact(
    worst_margin: WorstMargin,
    start: Mapping[str, int],
    bounds: Mapping[str, tuple[int, int]],
    step: int = GRID_STEP,
) -> ExactFit:
    """Grid point maximizing the smallest margin; ties favor the start.

    A coarse pass over every COARSE_STRIDE-th point raises the pruning floor
    before the exhaustive pass, which visits every grid point.
    """
    names = tuple(bounds)
    grids = [grid_points(*bounds[name], step) for name in names]
    if not all(grids):
        raise ValueError("search bounds contain no grid point")
    start_values = [start[name] for name in names]
    best: tuple[int, int, tuple[int, ...]] | None = None
    seen: set[tuple[int, ...]] = set()
    coarse = [grid[::COARSE_STRIDE] + grid[-1:] for grid in grids]
    for axes in (coarse, grids):
        for point in itertools.product(*axes):
            if point in seen:
                continue
            seen.add(point)
            floor = best[0] * -1 if best else -(10**18)
            worst = worst_margin(
                {**start, **dict(zip(names, point, strict=True))}, floor
            )
            if worst < floor:
                continue
            key = (-worst, deviation(point, start_values), point)
            if best is None or key < best:
                best = key
    if best is None:
        raise ValueError("no candidate was scored")
    return ExactFit({**start, **dict(zip(names, best[2], strict=True))}, -best[0])
