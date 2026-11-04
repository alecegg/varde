# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dominance_gating as dg

CTX = dg.Context(phi=96, c0=10, size_n=400, good_debts=[1, 2, 3, 4])


def test_share_excess_is_zero_up_to_half_the_file():
    assert dg.share_excess(50, 100) == 0
    assert dg.share_excess(100, 100) == 1


def test_gates_are_zero_for_comfortable_functions():
    fn = dg.Fn(tokens=80, cognitive=5, debt=1)
    assert dg.gate_hard(fn, 100, CTX) == 0
    assert dg.gate_ramp(fn, 100, CTX) == 0


def test_ramp_reaches_one_at_twice_the_comfort_limit():
    assert dg.gate_ramp(dg.Fn(192, 0, 1), 200, CTX) == 1
    assert 0 < dg.gate_ramp(dg.Fn(144, 0, 1), 200, CTX) < 1


def test_size_fade_and_rank():
    assert dg.gate_size(dg.Fn(1, 0, 1), 200, CTX) == 0.5
    assert dg.gate_rank(dg.Fn(1, 0, 2), 200, CTX) == 0.5


def test_percentile_interpolates():
    assert dg.percentile([1, 2, 3, 4, 5], 0.25) == 2
    assert dg.percentile([10, 20], 0.5) == 15


def test_extra_debt_applies_k_gate_and_share_excess():
    prep = dg.Prepared(100, 0, (dg.Fn(100, 0, 1000), dg.Fn(10, 0, 1000)))
    cand = dg.Candidate("x", dg.gate_none, 2.0)
    assert dg.extra_debt(prep, cand, CTX) == 2000
