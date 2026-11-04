"""Structured synthesis of extracted observations and open friction."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any

from .extract import (
    Budget,
    ModelResult,
    Runner,
    extract_with_claude,
    redact_mapping,
)
from .redact import redact

_INSTRUCTIONS = (
    "Synthesize JSON with findings.setup and findings.project arrays. "
    "Each finding must include title, evidence refs, and proposal. "
    "Classify Varde setup separately.\n"
)


def cap_synthesis_context(
    observations: list[Mapping[str, Any]],
    open_friction: list[Mapping[str, Any]],
    input_cap: int,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Select whole input records while counting the complete prompt against its cap."""
    selected_observations: list[Mapping[str, Any]] = []
    selected_friction: list[Mapping[str, Any]] = []
    for source, selected, other in (
        (observations, selected_observations, selected_friction),
        (open_friction, selected_friction, selected_observations),
    ):
        for record in source:
            candidate = [*selected, record]
            payload = (
                _payload(candidate, other)
                if selected is selected_observations
                else _payload(other, candidate)
            )
            full_prompt = f"varde-daily-review: {redact(_INSTRUCTIONS + payload)}"
            if _estimate_tokens(full_prompt) > input_cap:
                break
            selected.append(record)
    return selected_observations, selected_friction


def synthesize(
    observations: list[Mapping[str, Any]],
    open_friction: list[Mapping[str, Any]],
    *,
    budget: Budget,
    model_id: str | None = None,
    runner: Runner = subprocess.run,
) -> tuple[dict[str, list[dict[str, Any]]], ModelResult]:
    """Merge bounded context into redacted setup and project findings."""
    selected_observations, selected_friction = cap_synthesis_context(
        observations, open_friction, budget.synthesis_input_cap
    )
    prompt = _INSTRUCTIONS + _payload(selected_observations, selected_friction)
    findings: dict[str, list[dict[str, Any]]] = {"setup": [], "project": []}
    result = extract_with_claude(
        prompt,
        budget=budget,
        model_id=model_id,
        runner=runner,
        synthesis=True,
        structured_output=True,
    )
    if result.status != "ok" or result.text is None:
        return findings, result
    try:
        envelope = json.loads(result.text)
    except json.JSONDecodeError:
        return findings, _failed(result, "invalid synthesis JSON")
    source = envelope.get("findings") if isinstance(envelope, dict) else None
    if not isinstance(source, dict):
        return findings, _failed(result, "missing findings")
    for category in findings:
        rows = source.get(category)
        if isinstance(rows, list):
            findings[category] = [
                redact_mapping(row) for row in rows if isinstance(row, dict)
            ]
    sanitized_text = json.dumps({"findings": findings}, ensure_ascii=False)
    return findings, ModelResult(
        sanitized_text,
        result.tokens,
        result.cost_usd,
        result.status,
        result.error,
    )


def _payload(
    observations: list[Mapping[str, Any]],
    open_friction: list[Mapping[str, Any]],
) -> str:
    return json.dumps(
        {
            "observations": observations,
            "open_friction": open_friction,
        },
        ensure_ascii=False,
    )


def _estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _failed(result: ModelResult, error: str) -> ModelResult:
    return ModelResult(
        None,
        result.tokens,
        result.cost_usd,
        "failed",
        error,
    )
