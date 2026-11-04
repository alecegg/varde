"""judge() over hand-written measurement dicts; no browser."""

from copy import deepcopy

import pytest
from varde_design.judge import judge, judge_all, width_metrics
from varde_design.settings import Settings


def _metrics(scroll_width: int = 390, client_width: int = 390) -> dict:
    entry = {
        "width": 390,
        "doc": {"scroll_width": scroll_width, "client_width": client_width},
        "texts": [],
        "controls": [],
        "fonts": [],
        "headings": [],
        "paragraphs": [],
        "focus": None,
        "errors": [],  # each: {"kind": "console"|"pageerror", "text": str, "url": str}
        "truncated": None,
    }
    wide = deepcopy(entry) | {"width": 1440}
    wide["doc"] = {"scroll_width": 1440, "client_width": 1440}
    return {"schema": 1, "target": "page.html", "widths": [entry, wide]}


def test_clean_metrics_have_no_findings() -> None:
    assert judge_all(_metrics(), Settings()) == []


def test_overflow_is_an_r2_fail_at_that_width() -> None:
    findings = judge(_metrics(scroll_width=1200), 390, Settings())
    assert [(f.id, f.severity, f.width, f.file, f.tier) for f in findings] == [
        ("R2", "fail", 390, "page.html", "rendered")
    ]
    assert "810px" in findings[0].message


def test_one_pixel_of_rounding_is_tolerated() -> None:
    assert judge(_metrics(scroll_width=391), 390, Settings()) == []


def test_judge_only_reports_the_requested_width() -> None:
    assert judge(_metrics(scroll_width=1200), 1440, Settings()) == []
    assert len(judge_all(_metrics(scroll_width=1200), Settings())) == 1


def test_judge_is_deterministic_and_does_not_mutate() -> None:
    metrics = _metrics(scroll_width=1200)
    before = deepcopy(metrics)
    assert judge_all(metrics, Settings()) == judge_all(metrics, Settings())
    assert metrics == before


def test_unmeasured_width_is_an_error_not_a_pass() -> None:
    with pytest.raises(ValueError, match="768"):
        width_metrics(_metrics(), 768)
