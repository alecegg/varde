"""Pure selection, metric finding, and friction deduplication for sweeps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def select_unanalyzed(
    sessions: Iterable[Any], ledger: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    done = {(row.get("harness"), row.get("session")) for row in ledger}
    selected = []
    for session in sessions:
        rows = [session, *session.get("workers", [])]
        selected.extend(
            dict(row)
            for row in rows
            if (row.get("harness"), row.get("session_id")) not in done
        )
    return selected


def _finding(
    kind: str,
    evidence: Any,
    title: str,
    session_id: str,
    *,
    key_evidence: Any | None = None,
) -> dict[str, Any]:
    encoded = json.dumps(
        evidence if key_evidence is None else key_evidence,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    key = hashlib.sha256(f"{kind}:{encoded}".encode()).hexdigest()[:16]
    return {
        "kind": kind,
        "title": title,
        "dedupe_key": key,
        "evidence": evidence,
        "session": session_id,
    }


def findings_from_metrics(
    metrics: dict[str, Any], session_id: str = ""
) -> list[dict[str, Any]]:
    findings = []
    signals = metrics.get("signals", [])
    for signal in signals:
        kind = str(signal.get("kind", "waste"))
        findings.append(
            {
                **_finding(
                    kind, {"kind": kind}, f"Session efficiency: {kind}", session_id
                ),
                "estimated_seconds_saved": int(signal.get("count", 1)) * 30,
                "estimated_tokens_saved": int(metrics.get("output_tokens", 0))
                // max(len(signals), 1),
            }
        )
    for command, values in sorted(metrics.get("command_failures", {}).items()):
        failures, calls = int(values.get("failures", 0)), int(values.get("calls", 0))
        retries = int(values.get("retries", 0))
        if (
            failures
            or retries
            or values.get("timeouts")
            or values.get("permission_denials")
        ):
            evidence = {
                "command": command,
                "failures": failures,
                "calls": calls,
                "retries": retries,
                "timeouts": values.get("timeouts", 0),
                "permission_denials": values.get("permission_denials", 0),
            }
            findings.append(
                _finding(
                    "command_failure",
                    evidence,
                    f"Tool problems: {command}",
                    session_id,
                    key_evidence={"command": command},
                )
            )
            findings[-1]["estimated_seconds_saved"] = (
                failures * 30 + int(values.get("timeouts", 0)) * 60
            )
            findings[-1]["estimated_tokens_saved"] = 0
    return findings


def dedupe_against_open(
    findings: list[dict[str, Any]], friction_items: Iterable[Any]
) -> list[dict[str, Any]]:
    keys = set()
    for item in friction_items:

        def get(key, default=None, item=item):
            return (
                item.get(key, default)
                if isinstance(item, dict)
                else getattr(item, key, default)
            )

        if get("status") != "open":
            continue
        for occurrence in get("occurrences", []) or []:
            evidence = (
                occurrence.get("evidence", "")
                if isinstance(occurrence, dict)
                else getattr(occurrence, "evidence", "")
            )
            keys.update(
                part.split(":", 1)[1]
                for part in evidence.split()
                if part.startswith("sweep-key:")
            )
        key = get("dedupe_key")
        if key:
            keys.add(key)
    return [item for item in findings if item["dedupe_key"] not in keys]
