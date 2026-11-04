# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import score_separation as ss
import score_variants as sv

PROBLEMS = ("p", "q")


def toy_items() -> list[ss.Item]:
    items = [ss.Item(f"agreed:{p}", "good", p) for p in PROBLEMS]
    items += [ss.Item(f"proxy:{i}", "good") for i in range(8)]
    items += [ss.Item(f"k:{p}", "worse", p, "k") for p in PROBLEMS]
    items += [ss.Item("draft:p", "contested", "p")]
    return items


def toy_scores(good: float = 90.0, worse: float = 50.0) -> dict[str, float]:
    return {
        i.key: {"good": good, "worse": worse, "contested": 80.0}[i.role]
        for i in toy_items()
    }


def test_good_above_auc_orders_by_higher_score():
    assert ss.good_above_auc([90, 80], [10, 20]) == 1.0
    assert ss.good_above_auc([10], [90]) == 0.0
    assert ss.good_above_auc([50], [50]) == 0.5


def test_cut_line_keeps_ninety_percent_at_or_above():
    good = [float(v) for v in range(10)]
    cut = ss.cut_line(good)
    assert cut == 1.0
    assert ss.flagged_share(good, cut) == pytest.approx(0.1)
    with pytest.raises(ValueError, match="no good"):
        ss.cut_line([])


def test_paired_deltas_monotonic_share():
    paired = ss.paired_deltas(
        {"p": 90.0, "q": 80.0}, {"k": {"p": 50.0, "q": 85.0}, "j": {"p": 90.0}}
    )
    assert paired["k"]["deltas"] == {"p": 40.0, "q": -5.0}
    assert paired["k"]["monotonic"] == 0.5
    assert paired["j"]["monotonic"] == 0.0
    assert ss.overall_drop_share(paired) == pytest.approx(1 / 3)


def test_split_keeps_proxies_in_train_and_test():
    parts = ss.split_for_problem(toy_items(), PROBLEMS, "p")
    assert "agreed:p" in parts["test"]["good"]
    assert "agreed:p" not in parts["train"]["good"]
    assert "agreed:q" in parts["train"]["good"]
    assert "proxy:0" in parts["train"]["good"]
    assert "proxy:0" in parts["test"]["good"]
    assert parts["test"]["worse"] == ["k:p"]
    assert parts["test"]["contested"] == ["draft:p"]


def test_select_prefers_higher_train_auc_then_order():
    items = toy_items()
    tables = {"flat": toy_scores(70, 70), "sharp": toy_scores(90, 50)}
    part = ss.split_for_problem(items, PROBLEMS, "p")["train"]
    assert ss.select_candidate(tables, ["flat", "sharp"], part) == "sharp"
    tied = {"a": toy_scores(), "b": toy_scores()}
    assert ss.select_candidate(tied, ["a", "b"], part) == "a"


def test_lopo_selected_and_pooled():
    items = toy_items()
    tables = {"flat": toy_scores(70, 70), "sharp": toy_scores(90, 50)}
    folds = ss.lopo_selected(tables, ["flat", "sharp"], items, PROBLEMS)
    assert [f["chosen"] for f in folds] == ["sharp", "sharp"]
    total = ss.pooled(folds)
    assert total["auc"] == 1.0
    assert total["sens"] == 1.0
    assert total["by_kind"] == {"k": 1.0}
    fixed = ss.pooled(ss.lopo_fixed(tables["flat"], items, PROBLEMS))
    assert fixed["auc"] == 0.5


def test_cut_table_and_kind_sensitivity():
    items = toy_items()
    scores = toy_scores()
    row = ss.cut_table(scores, items, [60])[0]
    assert row["good_kept"] == 1.0
    assert row["worse_flagged"] == 1.0
    assert ss.sensitivity_by_kind(scores, items, 60.0) == {"k": 1.0}


def test_candidates_start_with_the_placeholder_default():
    found = sv.candidates()
    assert found[0].name == "placeholder|x1|gated"
    assert len({v.name for v in found}) == len(found) == 60


def test_calibrated_changes_a_copy_only():
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    tuned = sv.calibrated(base, sv.Variant("base-all", "all2", "gated"))
    params = tuned.languages["python"].parameters
    assert params["c0"] == 6 * sv.MICRO
    assert params["p0"] == 2 * sv.MICRO
    assert tuned.global_strengths["w"] == 2 * base.global_strengths["w"]
    assert tuned.global_strengths["names"] == 2 * sv.MICRO
    assert base.languages["python"].parameters["c0"] == 10 * sv.MICRO
    assert "p0" not in base.languages["python"].parameters


def test_gate_modes_change_confidence_and_fragments():
    record = {
        "structure_confidence": "low",
        "functions": [{"id": "a", "fragment_scope": "file"}],
    }
    assert sv.gated_record(record, "gated") == record
    ungated = sv.gated_record(record, "ungated")
    assert ungated["structure_confidence"] == "normal"
    assert ungated["functions"][0]["fragment_scope"] == "file"
    metrics = sv.gated_record(record, "ungated-metrics")
    assert metrics["functions"][0]["fragment_scope"] is None
    assert record["functions"][0]["fragment_scope"] == "file"


def test_merge_measures_adds_function_measures_and_confidence():
    facts = {"functions": [{"id": "a", "depth": None}], "tokens": 5}
    measured = {
        "functions": {"a": {"depth": 2}},
        "structure_confidence": "low",
        "import_fan_out": None,
        "call_coverage": {},
    }
    merged = sv.merge_measures(facts, measured)
    assert merged["functions"][0]["depth"] == 2
    assert merged["structure_confidence"] == "low"


def test_shipped_and_variant_paths_agree_on_the_default():
    source = "def f(a, b):\n    return a + b\n"
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    shipped = bm.score_source(source, "python")["score"]
    assert sv.score_of(sv.facts_record(source), base) == shipped
