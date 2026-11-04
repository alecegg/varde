"""Scan finding records and stable identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from varde_code.model import Span
from varde_code.rules.model import Rule, Severity


class Certainty(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Location:
    file: str
    span: Span


@dataclass
class Finding:
    id: str
    rule_id: str
    severity: Severity
    message: str
    location: Location
    evidence: Any
    remediation: str | None
    certainty: Certainty | None = None
    agent_instructions: str | None = None
    rewrite_status: str | None = None
    matched_file_state: FileState | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize in Rust struct field order, omitting optional nulls."""
        result: dict[str, Any] = {
            "id": self.id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "location": {
                "file": self.location.file,
                "span": _line_span(self.location.span),
            },
            "evidence": _ordered_json(self.evidence),
            "remediation": self.remediation,
        }
        if self.certainty is not None:
            result["certainty"] = self.certainty
        if self.agent_instructions is not None:
            result["agent_instructions"] = self.agent_instructions
        if self.rewrite_status is not None:
            result["rewrite_status"] = self.rewrite_status
        return result


def _ordered_json(value: Any) -> Any:
    if isinstance(value, dict):
        span = value.get("span")
        if isinstance(span, dict) and {"start_line", "end_line"} <= span.keys():
            value = {
                **value,
                "span": {
                    "start_line": span["start_line"],
                    "end_line": span["end_line"],
                },
            }
        return {key: _ordered_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_ordered_json(item) for item in value]
    return value


def _line_span(span: Span) -> dict[str, int]:
    return {"start_line": span.start_line, "end_line": span.end_line}


@dataclass(frozen=True)
class FileState:
    mtime_ns: int
    length: int

    @classmethod
    def of(cls, path: str | Path) -> FileState | None:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return cls(stat.st_mtime_ns, stat.st_size)


def resolve_real_path(walk_path: str | Path) -> Path:
    """Resolve a walked path to its absolute physical file when possible."""
    return Path(walk_path).resolve()


def finding_id(rule_id: str, file: str, span: Span) -> str:
    value = 0xCBF29CE484222325
    for part in (rule_id, file, str(span.start_byte), str(span.end_byte)):
        for byte in part.encode():
            value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def match_to_finding(rule: Rule, match: dict[str, Any], location: Location) -> Finding:
    return Finding(
        id=finding_id(rule.id, location.file, location.span),
        rule_id=rule.id,
        severity=rule.severity,
        message=rule.message,
        location=location,
        evidence=match.get("captures", {}),
        remediation=rule.remediation,
        certainty=Certainty.HIGH,
        agent_instructions=rule.fix,
    )
