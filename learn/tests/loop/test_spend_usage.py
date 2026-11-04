from datetime import datetime

from varde_learn.loop.diagnose.model import EvidenceRecord, RecordAnchor
from varde_learn.loop.review.spend_usage import aggregate, coverage, rows, weighted


def test_claude_streaming_rows_keep_last_snapshot_and_window_edges():
    records = [
        {
            "timestamp": f"2026-10-20T12:00:0{i}Z",
            "provider_message_id": "m1",
            "usage_record": {
                "input_tokens": 10,
                "cache_read_input_tokens": 4,
                "cache_creation_input_tokens": 3,
                "output_tokens": i,
            },
        }
        for i in (1, 2)
    ]
    parsed = rows(
        records,
        datetime.fromisoformat("2026-10-20T12:00:02+00:00"),
        datetime.fromisoformat("2026-10-20T12:00:02+00:00"),
    )
    assert parsed == [
        {
            "input": 10,
            "cache_read": 4,
            "cache_write": 3,
            "output": 2,
            "model": None,
            "timestamp": "2026-10-20T12:00:02Z",
            "context_size": 17,
            "provider_message_id": "m1",
        }
    ]


def test_harness_usage_fields_codex_pi_opencode_and_coverage():
    assert (
        rows(
            [
                {
                    "timestamp": "2026-10-20T00:00:00Z",
                    "usage_record": {
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 6,
                            "output_tokens": 2,
                        }
                    },
                }
            ]
        )[0]["input"]
        == 4
    )
    assert (
        rows(
            [
                {
                    "usage_record": {
                        "usage": {
                            "input": 10,
                            "cacheRead": 3,
                            "cacheWrite": 4,
                            "output": 2,
                        }
                    }
                }
            ]
        )[0]["context_size"]
        == 17
    )
    assert (
        rows(
            [
                {
                    "usage_record": {
                        "input_tokens": 5,
                        "cache_read_tokens": 2,
                        "cache_creation_input_tokens": 3,
                        "output_tokens": 1,
                    }
                }
            ]
        )[0]["cache_write"]
        == 3
    )
    assert (
        coverage("unknown", [{"usage_total": {"input_tokens": 12}}])["status"]
        == "session_total"
    )
    assert coverage("unknown", [])["status"] == "no_usage"


def test_weights_and_aggregate():
    item = {"input": 10, "cache_read": 20, "cache_write": 3, "output": 4}
    assert weighted(item) == 38
    assert aggregate([item]) == {
        "input": 10,
        "cache_read": 20,
        "cache_write": 3,
        "output": 4,
        "weighted": 38,
        "calls": 1,
    }


def test_codex_evidence_records_keep_each_call_in_a_multi_call_turn():
    anchor = RecordAnchor("source", 0, 0, 1, "digest", None)
    records = [
        EvidenceRecord(
            session_thread_id="thread",
            anchor=anchor,
            timestamp=f"2026-10-20T12:00:0{index}Z",
            kind="token_count",
            turn_id="same-turn",
            usage_last={
                "input_tokens": 100.0,
                "cached_input_tokens": 20.0,
                "cache_write_input_tokens": 4.0,
                "output_tokens": 3.0,
            },
            usage_total={"input_tokens": 100 * index},
        )
        for index in (1, 2, 3)
    ]
    parsed = rows(records)
    assert len(parsed) == 3
    assert parsed[0]["input"] == 80.0
    assert parsed[0]["cache_read"] == 20.0
    assert parsed[0]["cache_write"] == 4.0
    assert coverage("codex", records)["status"] == "per_call"


def test_zero_usage_record_and_naive_timestamp_use_utc_for_window():
    record = {
        "timestamp": "2026-10-20T12:00:00",
        "usage_last": {"input_tokens": 0, "output_tokens": 0},
        "usage_total": {"input_tokens": 0},
    }
    boundary = datetime.fromisoformat("2026-10-20T12:00:00+00:00")
    assert rows([record], boundary, boundary)[0]["input"] == 0
    assert coverage("codex", [record])["status"] == "per_call"


def test_dedupe_uses_provider_id_and_transcript_scope_only():
    records = [
        {
            "provider_message_id": "same",
            "transcript_id": "one",
            "usage_record": {"input_tokens": count},
        }
        for count in (1, 2)
    ] + [
        {
            "provider_message_id": "same",
            "transcript_id": "two",
            "usage_record": {"input_tokens": 3},
            "turn_id": "shared",
        }
    ]
    parsed = rows(records)
    assert len(parsed) == 2
    assert [row["input"] for row in parsed] == [2, 3]


def test_float_counts_and_cache_write_alias():
    parsed = rows(
        [
            {
                "usage_record": {
                    "usage": {
                        "input_tokens": 1.5,
                        "cache_write_input_tokens": 2.5,
                        "output_tokens": 3.5,
                    }
                }
            }
        ]
    )
    assert parsed[0]["input"] == 1.5
    assert parsed[0]["cache_write"] == 2.5
    assert parsed[0]["output"] == 3.5
