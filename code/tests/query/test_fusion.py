from __future__ import annotations

import pytest
from varde_code.query.fusion import fuse_rankings, rerank_files


def test_fuse_rankings_uses_reciprocal_rank_and_aggregates_entity_files() -> None:
    scores = fuse_rankings(
        [1, 2], [(10, -0.8), (11, -0.7), (12, -0.5)], {10: 3, 11: 3, 12: 2}
    )
    assert scores[1] == 1 / 61
    assert scores[2] == pytest.approx(2 / 62)
    assert scores[3] == pytest.approx(1 / 61)


def test_rerank_files_penalizes_noise_and_boosts_matching_entity_names() -> None:
    scores = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}
    paths = {
        1: "src/core.py",
        2: "tests/test_core.py",
        3: "vendor/core.py",
        4: "src/generated_core.py",
    }
    ranked = rerank_files(scores, paths, "core", {1: {"core"}})
    assert ranked == [1, 2, 4, 3]


def test_rerank_files_orders_penalized_candidates_after_clean_candidate() -> None:
    ranked = rerank_files(
        {1: 1.0, 2: 1.0},
        {1: "src/core.py", 2: "tests/test_core.py"},
        "unrelated",
        {},
    )
    assert ranked == [1, 2]
