# ruff: noqa: S101
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import measure_quantiles as mq


def test_nearest_rank_quantiles_carry_n():
    found = mq.quantiles(list(range(1, 101)))
    assert (found["q50"], found["q90"], found["q99"], found["n"]) == (50, 90, 99, 100)
    assert mq.quantiles([]) == {"q50": None, "q90": None, "q99": None, "n": 0}
    assert mq.quantiles([7])["q99"] == 7


def test_language_candidates_skip_tests_and_other_suffixes():
    assert mq.is_language_candidate("src/a.py", "python")
    assert not mq.is_language_candidate("tests/a.py", "python")
    assert not mq.is_language_candidate("src/test_a.py", "python")
    assert not mq.is_language_candidate("src/a.ts", "python")
    assert mq.is_language_candidate("src/a.cs", "csharp")
    assert not mq.is_language_candidate("node_modules/x/a.ts", "typescript")


def measured(rows, shares):
    return {"functions": rows, "file_measures": shares}


def test_language_report_columns_skip_none_values():
    rows = [
        {"max_nesting": 0, "vague_names": None},
        {"max_nesting": 2, "vague_names": None},
    ]
    shares = {"a.ts": {"delegation_share": None, "tokens_p50": 40}}
    report = mq.language_report([measured(rows, shares)])
    assert report["max_nesting"]["n"] == 2
    assert report["vague_names"]["n"] == 0
    assert report["delegation_share"]["n"] == 0
    assert report["tokens_p50"]["q50"] == 40
    assert (report["files"], report["functions"]) == (1, 2)


def row(delegates, tokens=10, fan_out=1):
    return {
        "delegates": delegates,
        "tokens": tokens,
        "fan_out": fan_out,
        "cognitive": 0,
    }


def test_flag_rate_is_strictly_above_the_cut():
    cut = Fraction(1, 7)
    assert mq.flag_rate([float(cut), 0.2, None, 0.0], cut) == {
        "n": 3,
        "flagged": 1,
        "rate": 1 / 3,
    }
    assert mq.flag_rate([None], cut)["rate"] is None


def test_proxy_comparison_and_problems():
    wrapped = [row(True), row(True), row(False, 80, 3)]
    # proxy sees only the small one-callee rows; the exact flag marks both
    exact_miss = [row(True, 90, 0), row(True, 90, 0), row(False, 80, 3)]
    comparison = mq.proxy_comparison(
        {
            "good": [[row(False, 80, 3)] * 8],
            "wrappers": [wrapped, exact_miss],
            "deep_chain": [wrapped],
        },
        Fraction(1, 7),
        Fraction(1, 3),
    )
    assert comparison["wrappers"]["proxy"] == {"n": 2, "flagged": 1, "rate": 0.5}
    assert comparison["wrappers"]["exact"] == {"n": 2, "flagged": 2, "rate": 1.0}
    assert comparison["wrappers"]["median"] == {"proxy": 0.0, "exact": 2 / 3}
    assert comparison["wrappers"]["exact_at_least_proxy"] == {"n": 2, "files": 2}
    assert mq.comparison_problems(comparison) == []
    comparison["good"]["exact"]["rate"] = 0.5
    assert mq.comparison_problems(comparison) == ["good: exact flag rate above 10%"]
    assert "no files" in mq.comparison_problems({})[0]


def test_check_problems_name_empty_python_measures():
    full = {"n": 3}
    ok = {
        "languages": {
            "python": dict.fromkeys((*mq.FUNCTION_MEASURES, *mq.FILE_MEASURES), full)
        }
    }
    assert mq.check_problems(ok) == []
    assert mq.check_problems({"languages": {}}) == [
        f"python {m}: n=0" for m in (*mq.FUNCTION_MEASURES, *mq.FILE_MEASURES)
    ]
