from varde_learn.loop.diagnose.metrics import session_metrics, waste_signals
from varde_learn.loop.diagnose.model import rendered_length_bytes


def call(command="cat /repo/a.py", output="ok", **kwargs):
    return {
        "kind": "tool_call",
        "timestamp": kwargs.pop("timestamp", "2026-10-18T12:00:00Z"),
        "tool_name": "Bash",
        "tool_input_excerpt": command,
        "tool_output_excerpt": output,
        "tool_use_id": kwargs.pop("tool_use_id", "tool-1"),
        **kwargs,
    }


def signal(records, kind):
    return next(item for item in waste_signals(records) if item.kind == kind)


def codex_pair(start, call_input, cached, output, total):
    """A real Codex model call: a token_usage_record row and a token_count row."""
    usage = {
        "input_tokens": call_input,
        "cached_input_tokens": cached,
        "output_tokens": output,
    }
    return [
        {
            "kind": "token_usage_record",
            "timestamp": start,
            "usage_record": {
                "thread_id": "t",
                "usage": usage,
                "thread_token_usage": total,
            },
        },
        {
            "kind": "token_count",
            "timestamp": start,
            "usage_last": usage,
            "usage_total": total,
        },
    ]


def test_codex_counts_each_model_call_once_with_per_call_peak():
    first_total = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 5}
    final_total = {"input_tokens": 300, "cached_input_tokens": 190, "output_tokens": 12}
    records = [
        *codex_pair("2026-10-18T12:00:00Z", 100, 40, 5, first_total),
        {"kind": "item_completed", "tool_status": "failed"},
        *codex_pair("2026-10-18T12:00:10Z", 200, 150, 7, final_total),
    ]
    metrics = session_metrics(records)
    assert metrics["model_calls"] == 2
    assert metrics["input_tokens"] == 300
    assert metrics["cached_input_tokens"] == 190
    assert metrics["output_tokens"] == 12
    assert metrics["peak_context"] == 200
    assert metrics["wall_seconds"] == 10
    assert metrics["tool_errors"] == 0


def test_session_metrics_sums_per_call_claude_usage_and_ignores_missing_usage():
    records = [
        {
            "kind": "message",
            "timestamp": "2026-10-18T12:00:00Z",
            "usage_record": {
                "input_tokens": 100,
                "cache_read_input_tokens": 20,
                "output_tokens": 30,
            },
        },
        {"kind": "tool_call", "tool_name": "Bash", "tool_status": "error"},
        {"kind": "message", "timestamp": "2026-10-18T12:00:10Z"},
    ]

    assert session_metrics(records) == {
        "model_calls": 1,
        "wall_seconds": 10,
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 30,
        "peak_context": 120,
        "tool_calls": 1,
        "tool_errors": 1,
    }


def test_repeat_read_requires_three_reads_of_same_file():
    rows = [call() for _ in range(3)]
    repeated = signal(rows, "repeat_read")
    assert repeated.count == 2
    assert [anchor["index"] for anchor in repeated.anchors] == [1, 2]
    assert not any(item.kind == "repeat_read" for item in waste_signals(rows[:2]))


def test_oversized_output_requires_uncaptured_output():
    small = call(output="x" * 3_000, tool_output_length_bytes=3_000)
    assert not any(item.kind == "oversized_output" for item in waste_signals([small]))
    big = call(output="x" * 5_000, tool_output_length_bytes=5_000)
    assert signal([big], "oversized_output").cost_tokens > 0
    captured = call(
        output="x" * 1_000 + "\ncapture handle: h123",
        tool_output_length_bytes=5_000,
    )
    assert not any(
        item.kind == "oversized_output" for item in waste_signals([captured])
    )


def test_rendered_output_length_uses_utf8_bytes():
    assert rendered_length_bytes("é") == 2


def test_oversized_output_with_unknown_original_length_does_not_fire():
    assert not any(
        item.kind == "oversized_output"
        for item in waste_signals([call(output="x" * 5_000)])
    )


def test_oversized_output_uses_each_opencode_tool_observation():
    row = {
        "kind": "assistant",
        "tool_observations": [
            {"output_excerpt": "x" * 4096, "output_length_bytes": 5_000},
            {
                "output_excerpt": "x" * 4096 + " capture handle: h123",
                "output_length_bytes": 5_000,
            },
            {"output_excerpt": "x" * 4096, "output_length_bytes": 4_096},
        ],
    }
    oversized = signal([row], "oversized_output")
    assert oversized.count == 2
    assert oversized.anchors == [
        {"index": 0, "timestamp": None},
        {"index": 0, "timestamp": None},
    ]


def test_opencode_tool_observations_do_not_turn_message_into_tool_call():
    metrics = session_metrics(
        [
            {
                "kind": "assistant",
                "tool_observations": [
                    {"tool_name": "bash", "output_excerpt": "result"},
                    {"tool_name": "read", "output_excerpt": "result"},
                ],
            }
        ]
    )
    assert metrics["tool_calls"] == 0


def test_rerun_for_detail_requires_different_filters():
    rows = [call("cat /repo/a.py | head -n 5"), call("cat /repo/a.py | tail -n 5")]
    assert signal(rows, "rerun_for_detail").count == 1
    assert not any(
        item.kind == "rerun_for_detail" for item in waste_signals([rows[0], rows[0]])
    )


def test_retry_loop_requires_three_consecutive_failures():
    rows = [call("git status", tool_status="error") for _ in range(3)]
    assert signal(rows, "retry_loop").count == 3
    assert not any(
        item.kind == "retry_loop"
        for item in waste_signals(
            rows[:2] + [call("git status", tool_status="success")]
        )
    )


def test_slow_command_uses_call_result_timestamps():
    rows = [
        call(timestamp="2026-10-18T12:00:00Z", tool_use_id="x"),
        {
            "kind": "tool_result",
            "timestamp": "2026-10-18T12:00:21Z",
            "tool_use_id": "x",
            "tool_output_excerpt": "done",
        },
    ]
    assert signal(rows, "slow_command").anchors == [
        {"index": 0, "timestamp": "2026-10-18T12:00:00Z"}
    ]
    rows[1]["timestamp"] = "2026-10-18T12:00:20Z"
    assert not any(item.kind == "slow_command" for item in waste_signals(rows))


def test_real_split_tool_records_pair_output_and_codex_uses_final_totals():
    rows = [
        {
            "kind": "tool_call",
            "timestamp": "2026-10-18T12:00:00Z",
            "tool_name": "Bash",
            "tool_input_excerpt": "cat /tmp/a",
        },
        {
            "kind": "tool_result",
            "timestamp": "2026-10-18T12:00:21Z",
            "tool_output_excerpt": "x" * 1_100,
            "tool_output_length_bytes": 5_000,
            "tool_status": "error",
        },
        {
            "kind": "token_count",
            "usage_total": {"input_tokens": 10, "output_tokens": 2},
        },
        {
            "kind": "token_count",
            "usage_total": {"input_tokens": 30, "output_tokens": 4},
        },
    ]
    metrics = session_metrics(rows)
    assert metrics["input_tokens"] == 30
    assert metrics["output_tokens"] == 4
    assert metrics["tool_calls"] == 1
    assert metrics["tool_errors"] == 1
    assert signal(rows, "oversized_output").anchors[0]["index"] == 0
    assert signal(rows, "slow_command").anchors[0]["index"] == 0


def test_claude_usage_counts_cache_creation_in_peak_context():
    metrics = session_metrics(
        [
            {
                "kind": "assistant",
                "usage_record": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 30,
                    "output_tokens": 5,
                },
            }
        ]
    )
    assert metrics["input_tokens"] == 100
    assert metrics["cached_input_tokens"] == 50
    assert metrics["peak_context"] == 150
