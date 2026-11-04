# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import score_variants as sv
import scorer_candidates as sc

MONOLITH = "def run(items):\n" + "".join(
    f"    if items[{i}]:\n        for x in items:\n            if x > {i}:\n"
    f"                items[{i}] += x\n"
    for i in range(14)
)


def test_gate_debt_drops_structure_only_at_low_confidence():
    costs = {"cognitive": 5, "depth": 7}
    assert sc.gate_debt(costs, low_confidence=False) == 12
    assert sc.gate_debt(costs, low_confidence=True) == 5


def test_dominance_debt_counts_only_functions_above_half_the_file():
    tokens = {"big": 900, "small": 50}
    debts = {"big": 100, "small": 100}
    assert sc.dominance_debt(debts, tokens, 1000, 0.0) == 0
    assert sc.dominance_debt(debts, tokens, 1000, 1.0) == 80
    assert sc.dominance_debt({"small": 100}, tokens, 1000, 2.0) == 0


def test_placeholder_candidate_equals_the_shipped_scope_score():
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    record = sv.facts_record(MONOLITH)
    shipped = bm.score_scope([record], base).files[0].gate_score / sc.MICRO
    assert sc.candidate_score(record, base, sc.CANDIDATES[0]) == shipped


def test_dominance_candidate_scores_a_monolith_below_the_placeholder():
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    record = sv.facts_record(MONOLITH)
    plain = sc.candidate_score(record, base, sc.CANDIDATES[0])
    dominated = sc.candidate_score(record, base, sc.Spec("D", dominance=2.0))
    assert dominated < plain
