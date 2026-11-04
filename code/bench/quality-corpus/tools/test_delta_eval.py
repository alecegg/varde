# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import delta_eval as de
import delta_eval_run as der

REFERENCE = [float(v) for v in range(50, 70)]  # 20 scores, p10 line = 51


def test_leave_one_out_excludes_the_file_itself():
    scores = [10.0, 20.0, 30.0, 40.0]
    assert de.leave_one_out(scores, 1) == [10.0, 30.0, 40.0]
    assert 20.0 not in de.leave_one_out(scores, 1)


def test_leave_one_out_changes_the_verdict_of_the_file_on_the_line():
    scores = [float(v) for v in range(1, 21)]  # p10 line is 2.0
    assert not de.below_p10(scores[1], scores)  # self-judged: sits on the line
    assert de.below_p10(scores[1], de.leave_one_out(scores, 1))  # line moves to 3.0


def test_identical_files_are_never_worse_than_before():
    for score in (0.0, 55.5, 100.0):
        assert not de.worse_than_before(score, score)
    assert de.worse_than_before(54.9, 55.0)
    assert not de.worse_than_before(55.0, 55.4, tolerance=0.5)
    assert de.worse_than_before(54.0, 55.0, tolerance=0.5)


def test_below_p10_uses_the_nearest_rank_line():
    assert de.below_p10(50.5, REFERENCE)
    assert not de.below_p10(51.0, REFERENCE)


def test_require_dev_refuses_other_splits():
    split = {"a": "dev", "b": "test-restricted", "c": "regression"}.__getitem__
    de.require_dev("a", split)
    for item in ("b", "c"):
        with pytest.raises(de.SplitError, match="only dev is readable"):
            de.require_dev(item, split)


def test_main_refuses_the_test_split(capsys):
    assert der.main(["--split", "test-restricted"]) == 2
    assert "refusing" in capsys.readouterr().err


def test_rate_lines_carry_n_and_empty_rates_do_not_divide():
    assert de.fmt(de.tally([True, False, False, False])) == "25% (1/4, n=4)"
    assert de.fmt(de.tally([])) == "- (n=0)"


def test_missing_n_flags_only_rate_cells_without_n():
    assert de.missing_n(["a | 12% (3/25, n=25)", "limit 10%: prose"]) == []
    assert de.missing_n(["a | 12% (3/25)"]) == ["a | 12% (3/25)"]


def test_p10_spread_is_deterministic_and_needs_enough_scores():
    scores = [float(v % 37) for v in range(60)]
    assert de.p10_spread(scores, 20) == de.p10_spread(scores, 20)
    assert de.p10_spread(scores, 20) != de.p10_spread(scores, 10)
    assert de.p10_spread(scores, 100)["n"] == 0


def test_tolerance_table_and_proposal():
    good = [0.1, -0.4, 0.0, -0.1, 0.2]  # after - before; two drops, 0.1 and 0.4
    table = de.tolerance_table(good, {"x": [-3.0, -0.2, 0.5]})
    first = table[0]
    assert first["good"] == de.rate(2, 5)
    assert first["flagged"]["x"] == de.rate(2, 3)
    assert table[1]["good"] == de.rate(0, 5)  # tolerance 0.5 clears both drops
    assert de.propose_tolerance(table) == 0.5


def test_distribution_reports_n_and_quantiles():
    view = de.distribution([float(v) for v in range(1, 11)])
    assert view["n"] == 10 and view["median"] == 5.0 and view["p90"] == 9.0
    assert de.distribution([])["n"] == 0
