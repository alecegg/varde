from __future__ import annotations

import math

from metrics import ndcg_at_k, tokens_to_first_hit


def test_ndcg_perfect_order_is_one() -> None:
    assert ndcg_at_k(["a", "b", "c"], {"a", "b"}) == 1.0


def test_ndcg_reversed_order_matches_hand_computation() -> None:
    expected = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert math.isclose(ndcg_at_k(["x", "a", "b"], {"a", "b"}, 3), expected)


def test_ndcg_empty_and_cutoff() -> None:
    assert ndcg_at_k(["a"], set()) == 0.0
    assert ndcg_at_k(["x", "a"], {"a"}, 1) == 0.0


def test_tokens_to_first_hit_includes_relevant_file() -> None:
    assert tokens_to_first_hit(["x", "a", "b"], {"a"}, {"x": 4, "a": 6}) == 10
    assert tokens_to_first_hit(["x"], {"a"}, {"x": 4}) is None
