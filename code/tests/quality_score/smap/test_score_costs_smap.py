from itertools import pairwise

from varde_code.quality_score.fixedpoint import MICRO, from_decimal
from varde_code.quality_score.smap import PLACEHOLDER_ANCHORS, score_density


def test_placeholder_map_is_monotone_bounded_and_clamped() -> None:
    values = [score_density(density) for density in range(0, 31 * MICRO, 10_000)]

    assert score_density(0) == 100 * MICRO
    assert values == sorted(values, reverse=True)
    assert all(0 <= score <= 100 * MICRO for score in values)
    assert score_density(-1) == 100 * MICRO
    assert score_density(100 * MICRO) == 0


def test_map_follows_anchors_without_interpolation_cliffs() -> None:
    for anchor in PLACEHOLDER_ANCHORS:
        assert score_density(anchor.density) == anchor.score
    for left, right in pairwise(PLACEHOLDER_ANCHORS):
        before = score_density(right.density - 1)
        at = score_density(right.density)
        assert (
            0
            <= before - at
            <= max(1, (left.score - right.score) // (right.density - left.density) + 1)
        )
    assert score_density(from_decimal("0.5")) < 100 * MICRO
