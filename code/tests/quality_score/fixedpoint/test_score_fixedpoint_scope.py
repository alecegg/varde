import random

from varde_code.quality_score.fixedpoint import (
    MICRO,
    ScopeScore,
    combine,
    meets_threshold,
    score_for_tokens,
)


def _tree(rng: random.Random, depth: int) -> ScopeScore:
    if depth == 0 or rng.random() < 0.35:
        tokens = rng.randint(1, 1000)
        return score_for_tokens(rng.randint(0, 100 * MICRO), tokens)
    return combine([_tree(rng, depth - 1) for _ in range(rng.randint(1, 4))])


def test_parent_rollups_equal_sums_for_random_trees() -> None:
    rng = random.Random(918273)  # noqa: S311 - Seeded randomness makes generated test trees reproducible.
    for _ in range(100):
        children = [_tree(rng, 4) for _ in range(rng.randint(1, 5))]
        parent = combine(children)

        assert parent.numerator == sum(child.numerator for child in children)
        assert parent.denominator == sum(child.denominator for child in children)


def test_threshold_uses_cross_multiplication() -> None:
    score = ScopeScore(75 * MICRO * 2, 3)

    assert meets_threshold(score, 50 * MICRO)
    assert not meets_threshold(score, 51 * MICRO)
