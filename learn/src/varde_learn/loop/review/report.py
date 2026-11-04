"""Render and persist redacted daily review reports."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

from .extract import redact_value
from .redact import redact


def render_report(
    findings: dict[str, list[dict[str, Any]]],
    *,
    run_date: date,
    locations: list[dict[str, Any]] | None = None,
    model_tokens: int = 0,
    cost_usd: float | None = None,
    token_spend: str | None = None,
) -> str:
    """Build a redacted markdown review with evidence references."""
    safe_findings = redact_value(findings)
    lines = [f"# Daily learn review: {run_date.isoformat()}", ""]
    for key, title in (("setup", "Varde setup"), ("project", "Project")):
        lines.extend((f"## {title}", ""))
        rows = safe_findings.get(key, [])
        if not rows:
            lines.extend(("No findings.", ""))
            continue
        for row in rows:
            lines.append(f"### {row.get('title', 'Untitled finding')}")
            proposal = row.get("proposal")
            if proposal:
                lines.extend(("", f"Proposal: {proposal}"))
            evidence = row.get("evidence", [])
            if isinstance(evidence, list) and evidence:
                refs = ", ".join(_evidence_ref(item) for item in evidence)
                lines.extend(("", f"Evidence: {refs}"))
            lines.append("")
    if locations:
        lines.extend(("## Locations", ""))
        lines.extend(
            f"- {location.get('harness', 'unknown')}: "
            f"{location.get('status', 'unknown')} - {location.get('reason', '')}"
            for location in redact_value(locations)
        )
        lines.append("")
    if token_spend:
        lines.extend((token_spend.rstrip(), ""))
    cost = f"${cost_usd:.6f}" if cost_usd is not None else "unknown"
    qualifier = "estimated "
    lines.extend(
        (
            "## Usage",
            "",
            f"Model tokens: {model_tokens}",
            f"{qualifier}Cost: {cost}",
            "",
        )
    )
    return redact("\n".join(lines))


def write_report(store_dir: str | Path, run_date: date, text: str) -> Path:
    """Write a redacted report under reviews/<date>.md."""
    path = Path(store_dir) / "reviews" / f"{run_date.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(text), encoding="utf-8")
    return path


def review_friction_key(finding: dict[str, Any]) -> str:
    """Return a stable review-key dedupe marker for a finding."""
    identity = "\0".join(
        (
            str(finding.get("category", "")),
            redact(str(finding.get("title", ""))).strip().lower(),
            redact(str(finding.get("proposal", ""))).strip().lower(),
        )
    )
    return "review-key:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def friction_evidence(finding: dict[str, Any]) -> str:
    """Format redacted report evidence for friction capture."""
    title = redact(str(finding.get("title", "Untitled finding")))
    proposal = redact(str(finding.get("proposal", "")))
    evidence = redact(str(finding.get("evidence", [])))
    body = redact(f"{title}\nProposal: {proposal}\nEvidence: {evidence}")
    return f"{body}\n{review_friction_key(finding)}"


def friction_candidates(
    findings: dict[str, list[dict[str, Any]]],
    existing_review_keys: set[str],
) -> list[dict[str, Any]]:
    """Prepare redacted friction payloads for findings not already recorded."""
    candidates = []
    for category in ("setup", "project"):
        for finding in findings.get(category, []):
            safe = redact_value(finding)
            safe["category"] = category
            key = review_friction_key(safe)
            if key in existing_review_keys:
                continue
            candidates.append(
                {
                    "review_key": key,
                    "title": safe.get("title", "Untitled finding"),
                    "evidence": friction_evidence(safe),
                }
            )
    return candidates


def _evidence_ref(value: Any) -> str:
    if not isinstance(value, dict):
        return redact(str(value))
    harness = redact(str(value.get("harness", "unknown")))
    session = redact(str(value.get("session_id", "unknown")))
    anchor = value.get("anchor", value.get("index", "?"))
    return f"{harness}/{session}#{redact(str(anchor))}"
