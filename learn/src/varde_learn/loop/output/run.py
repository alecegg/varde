"""Per-run transcript and timing extraction shared by output evals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from varde_learn.loop.output import extract_tokens, extract_transcript
from varde_learn.loop.redact import apply as redact_text


def write_run_artifacts(
    run_dir: Path,
    raw_value: dict[str, Any],
    *,
    harness: str,
    model: str | None,
    outcome: str,
    exit_code: int,
    timeout_seconds: int,
    elapsed_ms: int,
    trace_error: str | None = None,
    blocked_reason: str | None = None,
    blocked_detail: str | None = None,
    redacted: int = 0,
) -> dict[str, Any]:
    redacted_transcript = redact_text(extract_transcript(raw_value))
    transcript = redacted_transcript.text
    redacted += redacted_transcript.count
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "transcript.txt").write_text(transcript)
    (run_dir / "transcript.txt").write_text(transcript)
    measured, tokens = extract_tokens(raw_value)
    duration = raw_value.get("duration_ms")
    if not isinstance(duration, int) or duration < 0:
        duration = elapsed_ms
    timing = {
        "harness": harness,
        "model": model,
        "trace_error": trace_error,
        "duration_ms": duration,
        "tokens": tokens if measured else None,
        "outcome": outcome,
        "blocked_reason": blocked_reason,
        "blocked_detail": blocked_detail,
        "exit_code": exit_code,
        "timeout_seconds": timeout_seconds,
        "redacted": redacted,
    }
    (run_dir / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    return timing
