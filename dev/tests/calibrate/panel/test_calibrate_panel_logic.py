import pytest
from varde_dev.calibrate.panel import (
    assemble_prompt,
    build_call_specs,
    check_hygiene,
    map_verdict,
    parse_response,
    run_log_record,
)


def test_prompt_contains_only_supplied_rubric_notes_task_and_code() -> None:
    prompt = assemble_prompt(
        "Rubric body",
        "Idiomatic Python notes",
        "Return same behavior",
        ("a9f02c", "def first(): pass", "def second(): pass"),
        "BA",
    )

    assert "Rubric body" in prompt
    assert "Idiomatic Python notes" in prompt
    assert "Return same behavior" in prompt
    assert "PAIR ID: a9f02c" in prompt
    assert prompt.index("def second") < prompt.index("def first")
    assert "left.py" not in prompt


@pytest.mark.parametrize(
    "text",
    ["# over_split", "def golden(): pass", "Use sensible output", "Read src/file.py"],
)
def test_hygiene_excludes_forbidden_or_path_text(text: str) -> None:
    result = check_hygiene(text, "pass", "Do the same")

    assert result["excluded"]


def test_hygiene_excludes_comment_parity_mismatch() -> None:
    result = check_hygiene("# one comment\npass", "pass", "Do the same")

    assert result == {"excluded": True, "reasons": ["comment parity mismatch"]}


def test_hygiene_allows_matched_comment_lengths() -> None:
    result = check_hygiene("# alpha\npass", "# bravo\npass", "Do the same")

    assert result == {"excluded": False, "reasons": []}


def test_hygiene_counts_trailing_comments_and_flags_prompt_revealing_comments() -> None:
    mismatch = check_hygiene("value = 1  # brief", "value = 1", "Return value")
    revealing = check_hygiene(
        "value = 1  # helper extraction", "value = 1  # ordinary note", "Return value"
    )

    assert "comment parity mismatch" in mismatch["reasons"]
    assert "prompt-revealing comment" in revealing["reasons"]


@pytest.mark.parametrize("path", ["width/height", "10/2"])
def test_hygiene_does_not_treat_ratios_as_paths(path: str) -> None:
    assert not check_hygiene(f"return {path}", "return 1", "Return value")["excluded"]


def test_call_specs_make_both_orders_independent_with_configured_repeats() -> None:
    specs = build_call_specs(2)

    assert specs == [
        {"order": "AB", "repeat": 1, "left": "A", "right": "B"},
        {"order": "AB", "repeat": 2, "left": "A", "right": "B"},
        {"order": "BA", "repeat": 1, "left": "B", "right": "A"},
        {"order": "BA", "repeat": 2, "left": "B", "right": "A"},
    ]


def test_verdict_requires_acceptance_and_development_thresholds() -> None:
    assert map_verdict(
        [{"choice": "A", "confidence": "high"}] * 5
        + [{"choice": "B", "confidence": "low"}],
        "acceptance",
    ) == {"choice": "A", "confidence": "high", "valid_count": 6}
    assert (
        map_verdict([{"choice": "tie", "confidence": "high"}] * 4, "development")[
            "choice"
        ]
        == "tie"
    )
    assert (
        map_verdict(
            [{"choice": "A", "confidence": "high"}] * 2
            + [{"choice": "B", "confidence": "medium"}],
            "development",
        )["choice"]
        == "inconsistent"
    )
    assert (
        map_verdict(
            [{"choice": "A", "confidence": "high"}] * 5
            + [{"choice": "B", "confidence": "low"}],
            "acceptance",
        )["choice"]
        == "A"
    )
    assert (
        map_verdict(
            [{"choice": "A", "confidence": "high"}] * 3
            + [{"choice": "B", "confidence": "medium"}] * 2,
            "acceptance",
        )["choice"]
        == "inconsistent"
    )
    assert (
        map_verdict(
            [{"choice": "B", "confidence": "high", "order": "BA"}] * 4,
            "development",
        )["choice"]
        == "A"
    )
    assert (
        map_verdict(
            [
                {"choice": "A", "confidence": "high", "order": "AB"},
                {"choice": "B", "confidence": "high", "order": "BA"},
                {"choice": "A", "confidence": "medium", "order": "AB"},
                {"choice": "B", "confidence": "medium", "order": "BA"},
            ],
            "development",
        )["choice"]
        == "A"
    )


def test_response_validation_allows_one_retry_then_stops() -> None:
    assert parse_response("not json") == {
        "parsed": None,
        "parse_ok": False,
        "retry_count": 1,
        "retry": True,
    }
    assert parse_response('{"choice":"invalid","confidence":"high"}', 1) == {
        "parsed": None,
        "parse_ok": False,
        "retry_count": 1,
        "retry": False,
    }
    assert parse_response('{"choice":"B","confidence":"low"}') == {
        "parsed": {"choice": "B", "confidence": "low"},
        "parse_ok": True,
        "retry_count": 0,
        "retry": False,
    }


def test_log_record_requires_protocol_fields_and_preserves_hashes() -> None:
    fields = {
        "run_id": "run",
        "pair_id": "opaque",
        "lens": "lens-1",
        "lens_sha256": "a",
        "idiom_notes_sha256": "b",
        "model_id": "gpt-6-luna",
        "provider_version": None,
        "client_name": "codex",
        "client_version": "1",
        "temperature": None,
        "seed": None,
        "max_tokens": None,
        "top_p": None,
        "thinking_settings": {"effort": "medium"},
        "order": "AB",
        "seed_index": 1,
        "prompt_sha256": "prompt-hash",
        "system_prompt_sha256": "system-hash",
        "response_raw": "{}",
        "parsed": None,
        "parse_ok": False,
        "retry_count": 1,
        "tokens_in": None,
        "tokens_out": None,
        "request_id": None,
        "timestamp": "2026-10-17T00:00:00Z",
    }

    record = run_log_record(**fields)

    assert set(record) == set(fields)
    assert record["prompt_sha256"] == "prompt-hash"
    assert record["system_prompt_sha256"] == "system-hash"
    with pytest.raises(ValueError):
        run_log_record(run_id="incomplete")
