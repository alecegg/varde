# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import discrimination as dc


def test_auc_counts_ties_half():
    assert dc.auc([0, 1], [2, 3]) == 1.0
    assert dc.auc([2, 3], [0, 1]) == 0.0
    assert dc.auc([1, 1], [1, 1]) == 0.5
    assert dc.auc([], [1]) is None


def test_halfwidth_accepts_at_least_ninety_percent():
    devs = [float(i) for i in range(10)]
    assert dc.halfwidth(devs) == 8.0
    assert dc.halfwidth([0.0] * 4) == 0.0
    assert dc.caught([9.0, 8.0, 1.0], 8.0) == pytest.approx(1 / 3)


def test_analyse_flags_far_items_and_reports_by_type():
    good = {f"proxy:{i}": 10.0 + i * 0.1 for i in range(9)} | {"agreed:p": 10.0}
    worse = {"far": {"p": 20.0, "q": 0.0}, "near": {"p": 10.2}}
    cell = dc.analyse(10.4, good, worse, {"mono": 30.0}, ["agreed:p"])
    assert cell["accepted"] >= 0.9
    assert cell["by_type"] == {"far": 1.0, "near": 0.0}
    assert cell["auc"] > 0.5
    assert cell["contested_caught"] == 1.0
    assert cell["paired_up"] == {"far": 1.0, "near": 1.0}


def test_verdict_and_recommendation():
    cells = {"a": {"auc": 0.7, "caught": 0.1}, "b": {"auc": 0.6, "caught": 0.5}}
    assert dc.pick_recommended(cells) == "b"
    assert dc.verdict(0.6, 0.5) == "non-discriminating"
    assert dc.verdict(0.8, 0.5) == "discriminating"
    assert dc.verdict(0.8, 0.1) == "non-discriminating"
    assert dc.verdict(None, None) == "no-data"


def test_catch_matrix_uses_recommended_statistic():
    cells = {"m": {"s": {"by_type": {"k": 0.5}}, "t": {"by_type": {"k": 0.0}}}}
    assert dc.catch_matrix(cells, {"m": "s"}) == {"k": {"m": 0.5}}
