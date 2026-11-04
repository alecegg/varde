# ruff: noqa: S101
import sys
from pathlib import Path

import pytest
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.reference import CALIBRATION

sys.path.insert(0, str(Path(__file__).parent))
import measures_eval as me


def cell(rate, n=100):
    return {"rate": rate, "hits": 0 if rate is None else round(rate * n), "n": n}


def q(rate=1.0, inversions=0):
    return {"q4": cell(rate), "q5": {**cell(rate), "inversions": inversions}}


def result(pair_fp=0.03, good=0.10, gain=0.0, kind="guard_nesting", **over):
    base = {
        "pair_fp": cell(pair_fp),
        "good_product": cell(good),
        "kinds": {kind: {"below": cell(0.20 + gain)}},
        "q": {"python": q()},
        "agreed": {"agreed:a": 80.0},
        "monolith_below": cell(0.80),
        "drafts_below": cell(0.50),
        "file_loss": cell(0.02),
        "pairs_dev": {"after_higher": cell(0.60)},
    }
    return base | over


def test_config_grid_is_fixed_and_deterministic():
    names = [n for n, _ in me.config_names()]
    assert names == [n for n, _ in me.config_names()]
    assert names[0] == "off"
    assert dict(me.config_names())["off"] == {"sn": 0.0, "sm": 0.0, "sd": 0.0}
    assert len(names) == 1 + 3 * len(me.GRID) + len(me.GRID)


def test_with_strengths_sets_micro_units_and_leaves_the_rest():
    cal = load_calibration(CALIBRATION)
    changed = me.with_strengths(cal, {"sn": 0.5})
    assert changed.global_strengths["sn"] == 500_000
    assert changed.global_strengths["sm"] == cal.global_strengths["sm"]
    assert changed.languages is cal.languages


def test_test_split_is_refused():
    me.require_dev_split("dev")
    with pytest.raises(me.SplitError):
        me.require_dev_split("test")


def test_strength_ships_only_with_gain_and_within_budget():
    base = result()
    assert me.problems("sn=1", {"sn": 1.0}, base, result(gain=0.08)) == []
    assert any(
        "gain" in p for p in me.problems("sn=1", {"sn": 1.0}, base, result(gain=0.01))
    )


def test_false_positive_over_budget_blocks():
    base = result()
    bad = result(pair_fp=0.15, gain=0.2)
    assert any(
        "pair false positive" in p for p in me.problems("sn", {"sn": 1.0}, base, bad)
    )
    bad = result(good=0.20, gain=0.2)
    assert any("below-p10" in p for p in me.problems("sn", {"sn": 1.0}, base, bad))


def test_q_agreed_and_monolith_regressions_block():
    base = result()
    q_bad = result(gain=0.2, q={"python": q(0.9)})
    assert any("Q hurt" in p for p in me.problems("sn", {"sn": 1.0}, base, q_bad))
    inv = result(gain=0.2, q={"python": q(1.0, inversions=1)})
    assert any("inversions" in p for p in me.problems("sn", {"sn": 1.0}, base, inv))
    low = result(gain=0.2, agreed={"agreed:a": 79.0})
    assert any("agreed" in p for p in me.problems("sn", {"sn": 1.0}, base, low))
    mono = result(gain=0.2, drafts_below=cell(0.1))
    assert any("drafts_below" in p for p in me.problems("sn", {"sn": 1.0}, base, mono))


def test_file_loss_and_pair_regressions_block():
    base = result()
    lossy = result(gain=0.2, file_loss=cell(0.3))
    assert any(
        "losing points" in p for p in me.problems("sd", {"sd": 1.0}, base, lossy)
    )
    pairs = result(gain=0.2, pairs_dev={"after_higher": cell(0.50)})
    assert any("after>before" in p for p in me.problems("sd", {"sd": 1.0}, base, pairs))


def test_monolith_share_does_not_block():
    base = result()
    low = result(gain=0.2, monolith_below=cell(0.1))
    assert me.problems("sn", {"sn": 1.0}, base, low) == []


def test_file_loss_counts_drops_over_the_tolerance():
    cell_ = me.file_loss(
        {"a": 80.0, "b": 80.0, "c": 80.0}, {"a": 79.4, "b": 79.6, "c": 85.0}
    )
    assert (cell_["hits"], cell_["n"]) == (1, 3)


def test_decisions_skip_the_baseline_entry():
    baseline = result()
    out = me.decisions([("off", {}, baseline), ("sn=1", {"sn": 1.0}, result(gain=0.1))])
    assert list(out) == ["sn=1"]
    assert out["sn=1"] == []
