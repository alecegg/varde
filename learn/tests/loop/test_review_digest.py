from dataclasses import replace

from varde_learn.loop.diagnose.model import EvidenceRecord, RecordAnchor
from varde_learn.loop.review.digest import build_digest


def _record(index: int) -> EvidenceRecord:
    return EvidenceRecord(
        session_thread_id="session",
        anchor=RecordAnchor("source", index, 0, 0, "digest", None),
    )


def test_digest_redacts_tool_excerpt_and_summarizes_oversized_output() -> None:
    records = [
        replace(_record(4), role="user", text_excerpt="please inspect"),
        replace(
            _record(8),
            tool_name="shell",
            tool_output_excerpt='{"password": "hunter2hunter2"}',
            tool_output_length_bytes=9000,
            detail_truncated=True,
            tool_status="failed",
        ),
    ]
    digest = build_digest(records, 1000)
    assert "[4]" in digest and "[8]" in digest
    assert "hunter2hunter2" not in digest
    assert "oversized output, 9000 bytes" in digest
    assert build_digest(records, 1000) == digest


def test_digest_obeys_small_character_limit_without_partial_anchor() -> None:
    digest = build_digest(
        [replace(_record(1234), role="user", text_excerpt="x" * 500)], 5
    )
    assert digest == ""


def test_digest_redacts_before_truncation_and_marks_retry_timeout() -> None:
    digest = build_digest(
        [
            replace(
                _record(7),
                tool_name="shell",
                tool_output_excerpt="x" * 500 + " MY_KEY=secretvalue",
                tool_status="timed_out",
                failure_reason="retry after failure",
            )
        ],
        700,
    )
    assert "secretvalue" not in digest
    assert "retry" in digest and "timeout" in digest


def test_digest_redacts_secrets_in_tool_names_and_path_segments() -> None:
    digest = build_digest(
        [
            replace(
                _record(9),
                tool_name="sk-ant-12345678901234567890123456789012",
                tool_output_excerpt="reading /tmp/TOKEN=abcdefgh12345/output",
            )
        ],
        700,
    )
    assert "sk-ant-123" not in digest
    assert "abcdefgh12345" not in digest
