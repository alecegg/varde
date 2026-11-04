"""Pure helpers for the one-line scan report; no I/O."""

from __future__ import annotations

SEVERITIES = ("error", "warning", "info")
INDEX_CODES = ("index_missing", "index_stale")


class ReportError(Exception):
    """The scan output cannot be summarized."""


def _scan_data(result: object) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise ReportError("scan returned invalid output")
    return result["data"]


def summary_line(result: object, build_seconds: int, scan_seconds: int) -> str:
    """Return the report line for a scan result; raise ``ReportError`` if unusable."""
    data = _scan_data(result)
    analysis, gate, findings = (
        data.get("analysis"),
        data.get("gate"),
        data.get("findings"),
    )
    if not (
        isinstance(analysis, dict)
        and isinstance(gate, dict)
        and isinstance(findings, list)
    ):
        raise ReportError("scan returned invalid output")
    counts = {
        severity: sum(
            1
            for finding in findings
            if isinstance(finding, dict) and finding.get("severity") == severity
        )
        for severity in SEVERITIES
    }
    if not (isinstance(result, dict) and result.get("ok") is True):
        raise ReportError("scan tool returned an error")
    if analysis.get("status") != "complete" or gate.get("status") not in (
        "pass",
        "fail",
    ):
        raise ReportError("scan analysis is incomplete or gate status is unknown")
    return (
        f"gate={gate['status']} analysis={analysis['status']} "
        f"errors={counts['error']} warnings={counts['warning']} "
        f"info={counts['info']} build={build_seconds}s scan={scan_seconds}s"
    )


def index_error_code(result: object) -> str:
    """Return ``index_missing``/``index_stale`` from the result's error, else ``""``."""
    if not isinstance(result, dict):
        return ""
    error = result.get("error")
    if not error:
        data = result.get("data")
        error = data.get("error") if isinstance(data, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if code in INDEX_CODES else ""
