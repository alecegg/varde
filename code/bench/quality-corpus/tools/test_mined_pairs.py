# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mined_pairs as mp


def test_sign_test_symmetric_and_extreme():
    assert mp.sign_test_p(0, 0) == 1.0
    assert mp.sign_test_p(5, 5) == 1.0
    assert abs(mp.sign_test_p(10, 0) - 2 / 1024) < 1e-12


def test_paired_stats_counts_ties():
    s = mp.paired_stats([1.0, -1.0, 0.0, 2.0])
    assert (s["up"], s["tie"], s["down"]) == (0.5, 0.25, 0.25)
    assert s["mean"] == 0.5 and s["median"] == 0.5


def test_intent_tags_and_size():
    assert mp.intent_tags("Simplified loop; early return") == [
        "simplify",
        "early return",
    ]
    assert mp.size_bucket(999) == "<1k tokens" and mp.size_bucket(5000) == ">=3k"


def test_function_name_and_changed_density():
    assert mp.function_name("module.py::A.f#1") == "f"
    debts = {"module.py::A.f#1": 5, "module.py::g#1": 7}
    tokens = {"module.py::A.f#1": 10, "module.py::g#1": 20}
    assert mp.changed_density(debts, tokens, {"f"}) == (5, 10)
    assert mp.changed_density(debts, tokens, {"zzz"}) is None


def test_hit_and_chance():
    assert mp.hit([], {"f"}) is None
    assert mp.hit(["m::f#1"], {"f"}) is True
    assert mp.chance_hit(10, 10) == 1.0
    assert abs(mp.chance_hit(4, 1) - 0.75) < 1e-12


def test_cut_accuracy():
    assert mp.cut_accuracy([60, 80], [90, 50], 70) == 0.5
