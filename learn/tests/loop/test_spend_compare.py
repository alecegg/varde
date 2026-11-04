from varde_learn.loop.review.spend_compare import compare


def test_compare_reports_movement_noise_and_missing_previous():
    window = {"start": "2026-10-22T00:00:00+00:00", "end": "2026-10-22T23:59:59+00:00"}
    current = {
        "window": window,
        "totals": {
            "input": 110,
            "cache_read": 100,
            "cache_write": 100,
            "output": 100,
            "weighted": 100,
            "calls": 4,
        },
    }
    previous = {
        "window": window,
        "totals": {
            "input": 100,
            "cache_read": 100,
            "cache_write": 100,
            "output": 100,
            "weighted": 100,
            "calls": 4,
        },
    }
    result = compare(previous, current)
    assert result["metrics"]["input"]["change"] == "up"
    assert result["metrics"]["cache_read"]["change"] == "unchanged"
    assert compare(None, current)["status"] == "no_previous"


def test_compare_refuses_different_windows_and_reports_missing_metrics():
    previous = {
        "window": {
            "start": "2026-10-20T00:00:00+00:00",
            "end": "2026-10-20T23:59:59+00:00",
        },
        "totals": {"input": 10},
    }
    current = {
        "window": {
            "start": "2026-10-22T00:00:00+00:00",
            "end": "2026-10-22T23:59:59+00:00",
        },
        "totals": {"input": 10},
    }
    assert compare(previous, current)["status"] == "compared"
    current["window"]["end"] = "2026-10-22T12:00:00+00:00"
    assert compare(previous, current)["status"] == "not_comparable"


def test_compare_marks_missing_metrics_unavailable():
    window = {"start": "2026-10-22T00:00:00+00:00", "end": "2026-10-22T23:59:59+00:00"}
    result = compare(
        {"window": window, "totals": {"input": 1}},
        {"window": window, "totals": {"input": 1}},
    )
    assert result["metrics"]["cache_read"]["change"] == "unavailable"
