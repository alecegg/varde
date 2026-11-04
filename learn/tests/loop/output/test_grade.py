from __future__ import annotations

from varde_learn.loop.output.grade import (
    grade_results,
    parse_judge_results,
    strip_code_fences,
)


def test_strip_code_fences_and_parse_judge_results() -> None:
    payload = (
        '```json\n{"results":[{"assertion":"a","verdict":"PASS",'
        '"evidence":"line"}, null]}\n```'
    )
    assert (
        strip_code_fences(payload)
        == '{"results":[{"assertion":"a","verdict":"PASS","evidence":"line"}, null]}'
    )
    assert parse_judge_results(payload) == [
        {"assertion": "a", "verdict": "PASS", "evidence": "line"}
    ]
    assert parse_judge_results("not json") == []


def test_grade_results_merges_results_and_fails_ungraded_assertions() -> None:
    result = grade_results(
        ["verified", "judged", "missing"],
        [{"assertion": "verified", "verdict": "PASS", "evidence": "ok"}],
        [{"assertion": "judged", "verdict": "FAIL", "evidence": "absent"}],
    )
    assert result["total"] == 3
    assert result["passed"] == 1
    assert [item["verdict"] for item in result["results"]] == ["PASS", "FAIL", "FAIL"]
    assert result["results"][-1]["evidence"] == "No grading result returned"


def test_failed_run_cannot_pass_assertions() -> None:
    result = grade_results(["a"], [], [{"assertion": "a", "verdict": "PASS"}], "failed")
    assert result["passed"] == 0
    assert result["results"][0]["verdict"] == "FAIL"
