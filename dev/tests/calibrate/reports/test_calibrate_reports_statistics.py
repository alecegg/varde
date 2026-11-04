from itertools import product

import pytest
from varde_dev.calibrate.reports import (
    PANEL_LABEL_TRUTH_TABLE,
    VERDICTS,
    accuracy,
    cluster_bootstrap_interval,
    cohens_kappa,
    panel_label,
    wilson_interval,
)


def test_accuracy_and_kappa_on_hand_computed_labels() -> None:
    assert accuracy(["A", "B", "A", "B"], ["A", "A", "A", "B"]) == 0.75
    assert cohens_kappa(["A", "B", "A", "B"], ["A", "A", "A", "B"]) == pytest.approx(
        0.5
    )


def test_wilson_interval_for_two_of_four() -> None:
    assert wilson_interval(2, 4) == pytest.approx((0.1500, 0.84996), abs=0.0001)


def test_wilson_interval_for_eight_of_ten_and_zero_of_five() -> None:
    assert wilson_interval(8, 10) == pytest.approx((0.4902, 0.9433), abs=0.0001)
    assert wilson_interval(0, 5) == pytest.approx((0.0, 0.4345), abs=0.0001)


def test_cluster_bootstrap_reflects_cluster_variance_and_seed() -> None:
    variable_clusters = [
        [("A", "A"), ("A", "A")],
        [("A", "A"), ("A", "A")],
        [("A", "B"), ("A", "B")],
        [("A", "B"), ("A", "B")],
    ]
    fixed_clusters = [
        [("A", "A"), ("B", "A")],
        [("A", "A"), ("B", "A")],
        [("A", "A"), ("B", "A")],
        [("A", "A"), ("B", "A")],
    ]
    interval = cluster_bootstrap_interval(
        variable_clusters, accuracy, replicates=4, seed=1
    )
    assert interval == (0.0, 0.75)
    assert interval[0] <= 0.5 <= interval[1]
    assert (
        cluster_bootstrap_interval(variable_clusters, accuracy, replicates=4, seed=1)
        == interval
    )
    assert cluster_bootstrap_interval(
        variable_clusters, accuracy, replicates=4, seed=2
    ) == (0.25, 0.75)
    fixed_interval = cluster_bootstrap_interval(
        fixed_clusters, accuracy, replicates=4, seed=1
    )
    assert fixed_interval == (0.5, 0.5)
    assert interval[1] - interval[0] > fixed_interval[1] - fixed_interval[0]


def test_panel_truth_table_covers_each_verdict_vector_once() -> None:
    vectors = list(product(VERDICTS, repeat=3))
    assert len(PANEL_LABEL_TRUTH_TABLE) == 64
    assert set(PANEL_LABEL_TRUTH_TABLE) == set(vectors)
    assert set(PANEL_LABEL_TRUTH_TABLE.values()) == {
        "unanimous",
        "decisive",
        "panel-tie",
        "contested",
    }
    for votes in vectors:
        label, dissent = panel_label(votes)
        assert label == PANEL_LABEL_TRUTH_TABLE[votes]
        if label == "unanimous":
            assert votes[0] in {"A", "B"} and len(set(votes)) == 1
            assert dissent == ()
        elif label == "decisive":
            assert votes.count("A") == 2 or votes.count("B") == 2
            assert len(dissent) == 1
        elif label == "panel-tie":
            assert votes.count("tie") >= 2
            assert dissent == ()
        else:
            assert votes.count("tie") < 2
            assert votes.count("A") < 2 and votes.count("B") < 2
            assert dissent == ()


def test_panel_label_rejects_incomplete_vectors() -> None:
    with pytest.raises(ValueError):
        panel_label(["A", "B"])
