# pyright: reportOptionalSubscript=false
import pytest
from varde_learn.loop.review.spend_waste import analyze


def usage(weight: int, context: int, **extra):
    return {
        "input": weight,
        "cache_read": 0,
        "cache_write": 0,
        "output": 0,
        "context_size": context,
        **extra,
    }


def session(session_id: str, *rows, **metadata):
    return {"session_id": session_id, "rows": list(rows), **metadata}


def test_context_bands_share_peak_and_thresholds():
    report = analyze([session("s", usage(100, 200_001), usage(300, 400_001))])
    assert report["context_over_200k"] == {
        "name": "context_over_200k",
        "weighted_share": 1.0,
        "count": 2,
        "thresholds": {"context_tokens": 200_000, "peak_context_tokens": 400_001},
    }
    assert report["context_over_400k"]["weighted_share"] == 0.75
    assert report["context_over_400k"]["count"] == 1


def test_turn_categories_use_per_call_tool_names_and_none_without_names():
    report = analyze(
        [
            session(
                "s",
                usage(100, 1),
                usage(100, 1),
                tool_names=["Monitor", "Bash"],
            )
        ]
    )
    assert report["poll_watch_msg_read_sleep"]["weighted_share"] == 0.5
    assert analyze([session("s", usage(100, 1))])["msg_send"] is None
    send = analyze([session("send", usage(100, 1), tool_names=["msg-send"])])
    assert send["msg_send"]["weighted_share"] == 1.0
    shell = analyze(
        [
            session(
                "shell",
                usage(100, 1),
                usage(100, 1),
                tool_names=["Bash", "Bash"],
            )
        ]
    )
    assert shell["poll_watch_msg_read_sleep"] is None
    assert shell["msg_send"] is None


def test_startup_and_repeated_reviewer_sessions_and_idle_cache():
    report = analyze(
        [
            session(
                "a",
                usage(
                    100,
                    50,
                    timestamp="2026-10-20T10:00:00",
                ),
                usage(
                    100,
                    60,
                    timestamp="2026-10-20T12:00:01+00:00",
                    cache_write=70_001,
                ),
                role="reviewer/checker",
                target="T",
                first_call_context=50,
            ),
            session(
                "b",
                usage(200, 70, timestamp="2026-10-20T10:00:00Z"),
                role="reviewer/checker",
                target="T",
                first_call_context=70,
            ),
            session(
                "c",
                usage(400, 80, timestamp="2026-10-20T11:00:00Z"),
                role="builder",
                target="T",
                first_call_context=80,
            ),
        ]
    )
    assert report["startup_prompt"]["weighted_share"] == pytest.approx(700 / 140_802)
    assert report["startup_prompt"]["count"] == 3
    assert report["repeated_review_rounds"]["count"] == 1
    assert report["repeated_review_rounds"]["weighted_share"] == pytest.approx(
        200 / 140_802
    )
    assert report["cache_rebuild_after_idle"]["count"] == 1
    assert report["cache_rebuild_after_idle"]["thresholds"] == {
        "idle_seconds": 3600,
        "cache_write_tokens": 60000,
    }


def test_missing_metadata_context_and_partial_usage_are_safe():
    report = analyze([session("s", {"input": 100})])
    assert report["context_over_200k"] is None
    assert report["startup_prompt"] is None
    assert report["repeated_review_rounds"] is None
    assert report["subagent"] is None
    assert report["cache_rebuild_after_idle"] is None
