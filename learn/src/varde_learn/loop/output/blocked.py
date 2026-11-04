"""Classify harness outcomes that make a run inconclusive."""

from __future__ import annotations

import json
from typing import Any


def classify(
    trace: Any = None,
    trace_error: str | None = None,
    setup_error: str | None = None,
    stderr: str | None = None,
) -> str | None:
    if setup_error is not None:
        return "fixture_setup_failure"
    error_event = ""
    if isinstance(trace, dict) and (
        trace.get("is_error") is True or trace.get("type") in {"error", "turn.failed"}
    ):
        error_event = json.dumps(trace).lower()
    text = " ".join((trace_error or "", stderr or "", error_event)).lower()
    for reason, terms in (
        (
            "sandbox_denial",
            ("sandbox denied", "sandbox denial", "operation not permitted"),
        ),
        (
            "reviewer_launch_failure",
            (
                "reviewer failed to launch",
                "reviewer launch failed",
                "failed to launch reviewer",
            ),
        ),
        ("stale_approval", ("stale approval", "approval is stale", "approval expired")),
        (
            "tool_launch_failure",
            ("tool failed to launch", "tool launch failed", "failed to launch tool"),
        ),
        (
            "unavailable_app",
            (
                "application unavailable",
                "app unavailable",
                "command not found",
                "failed to launch",
            ),
        ),
    ):
        if any(term in text for term in terms):
            return reason
    return None
