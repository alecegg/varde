"""Monotone piecewise-linear score map using integer micro-units."""

from dataclasses import dataclass
from itertools import pairwise

from ..fixedpoint import MICRO, from_decimal


@dataclass(frozen=True, order=True)
class Anchor:
    density: int
    score: int


PLACEHOLDER_ANCHORS = (
    Anchor(from_decimal("0"), from_decimal("100")),
    Anchor(from_decimal("1"), from_decimal("90")),
    Anchor(from_decimal("5"), from_decimal("70")),
    Anchor(from_decimal("10"), from_decimal("40")),
    Anchor(from_decimal("20"), from_decimal("10")),
    Anchor(from_decimal("30"), from_decimal("0")),
)


def score_density(
    density: int, anchors: tuple[Anchor, ...] = PLACEHOLDER_ANCHORS
) -> int:
    """Return an integer micro-score for a density in micro-units."""
    _validate(anchors)
    if density <= 0:
        return 100 * MICRO
    for left, right in pairwise(anchors):
        if density <= right.density:
            width = right.density - left.density
            delta = left.score - right.score
            return max(0, left.score - (density - left.density) * delta // width)
    return 0


def _validate(anchors: tuple[Anchor, ...]) -> None:
    if len(anchors) < 2 or anchors[0].density != 0 or anchors[0].score != 100 * MICRO:
        raise ValueError("anchors must start at density 0, score 100")
    for left, right in pairwise(anchors):
        if (
            right.density <= left.density
            or right.score > left.score
            or left.score > 100 * MICRO
        ):
            raise ValueError(
                "anchors must have increasing density and non-increasing scores"
            )
