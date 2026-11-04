# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import guidance_run as gr
from varde_code.quality_score.calibration import load_calibration

SOURCES = gr.agreed_sources()
CALIBRATION = load_calibration(bm.DEFAULT_CALIBRATION)


def test_largest_picks_biggest_rise_among_allowed_with_name_tiebreak():
    increase = {"names": 5, "params": 5, "cognitive": 9, "depth": -3}
    assert gr.largest(increase, ["names", "params"]) == "names"
    assert gr.largest(increase, ["depth"]) is None
    assert gr.largest(increase, ["cognitive", "names"]) == "cognitive"


def test_loss_increase_covers_both_sides():
    assert gr.loss_increase({"a": 1}, {"a": 4, "b": 2}) == {"a": 3, "b": 2}


def test_touched_ids_are_new_or_changed_functions():
    def fn(i, tokens):
        return {"id": i, "tokens": tokens}

    assert gr.touched_ids(
        [fn("a", 5), fn("b", 6)], [fn("a", 5), fn("b", 9), fn("c", 1)]
    ) == {"b", "c"}


def test_top_hit_and_rate_skip_file_level_categories():
    assert gr.top_hit(["a", "b"], {"b"}) is True
    assert gr.top_hit(["a"], {"b"}) is False
    assert gr.top_hit([], {"b"}) is None
    assert gr.rate([True, False, None]) == 0.5
    assert gr.rate([None]) is None


@pytest.mark.parametrize(
    ("kind", "category"), [("rename_vague", "names"), ("add_params", "params")]
)
def test_single_property_degradations_are_attributed_and_hit(kind, category):
    result = gr.evaluate(SOURCES["notifier"], kind, CALIBRATION)
    assert result["attributed_core"] == category
    assert result["hit"] is True
    assert result["recovery_revert"] > 0
    worst = next(c for c in result["view"]["categories"] if c["name"] == category)
    assert worst["worst"]
    assert all(item["action"] for item in worst["worst"])


def test_noop_degradation_is_dropped_and_summary_has_every_kind():
    results, summary = gr.run({"notifier": SOURCES["notifier"]}, CALIBRATION)
    assert set(summary) == {r["kind"] for r in results}
    assert "rename_vague" in summary
    assert gr.format_report(summary).startswith("type")
