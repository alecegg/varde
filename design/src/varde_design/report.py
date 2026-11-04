"""Finding record, versioned JSON report envelope, validation, and exit codes."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .registry import META_FINDING_IDS, RULES_BY_ID

SCHEMA_VERSION = 1
COMMANDS = ("check", "tokens", "survey")
SEVERITIES = ("fail", "warn")
EXIT_CLEAN, EXIT_NOT_CHECKED, EXIT_FAIL = 0, 1, 2

_FINDING_KEYS = (
    "id",
    "severity",
    "tier",
    "file",
    "line",
    "selector",
    "width",
    "snippet",
    "message",
)
_CHECKED_KEYS = (
    "tiers",
    "widths",
    "settings_source",
    "elements",
    "truncated",
    "not_run",
)


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    tier: str
    file: str
    message: str
    line: int | None = None
    selector: str | None = None
    width: int | None = None
    snippet: str = ""


def checked_block(  # noqa: PLR0913
    *,
    tiers: list[str],
    widths: list[int],
    settings_source: str,
    elements: int = 0,
    truncated: tuple[int, int] | None = None,
    not_run: list[str] | None = None,
    rendered: bool = False,
    notes: list[str] | None = None,
) -> dict[str, object]:
    """The checked: block; truncated is (shown, total) or None."""
    return {
        "tiers": tiers,
        "widths": widths,
        "rendered": rendered,
        "settings_source": settings_source,
        "elements": elements,
        "truncated": None
        if truncated is None
        else {"shown": truncated[0], "total": truncated[1]},
        "not_run": not_run or [],
        "notes": notes or [],
    }


def build_report(
    command: str,
    findings: list[Finding],
    checked: dict[str, object],
    data: dict[str, object] | None = None,
) -> dict[str, object]:
    """JSON envelope shared by check, tokens and survey; data is per command."""
    return {
        "schema": SCHEMA_VERSION,
        "command": command,
        "findings": [asdict(finding) for finding in findings],
        "checked": checked,
        "data": data or {},
    }


def exit_code(report: dict[str, object]) -> int:
    """2 for any fail finding, 1 when anything was not checked, else 0."""
    findings: list[dict[str, object]] = report["findings"]  # type: ignore[assignment]
    checked: dict[str, object] = report["checked"]  # type: ignore[assignment]
    if any(item["severity"] == "fail" for item in findings):
        return EXIT_FAIL
    if checked["not_run"] or checked["truncated"]:
        return EXIT_NOT_CHECKED
    return EXIT_CLEAN


def _missing(label: str, obj: object, keys: tuple[str, ...]) -> list[str]:
    if not isinstance(obj, dict):
        return [f"{label}: expected an object"]
    return [f"{label}: missing key {key}" for key in keys if key not in obj]


def _finding_errors(index: int, finding: object) -> list[str]:
    label = f"findings[{index}]"
    errors = _missing(label, finding, _FINDING_KEYS)
    if errors or not isinstance(finding, dict):
        return errors
    if finding["id"] not in RULES_BY_ID and finding["id"] not in META_FINDING_IDS:
        errors.append(f"{label}: unknown rule id {finding['id']!r}")
    if finding["severity"] not in SEVERITIES:
        errors.append(f"{label}: severity must be fail or warn")
    return errors


def validate_report(report: object) -> list[str]:
    """Return schema errors for a report (empty list when valid)."""
    errors = _missing(
        "report", report, ("schema", "command", "findings", "checked", "data")
    )
    if errors or not isinstance(report, dict):
        return errors
    if report["schema"] != SCHEMA_VERSION:
        errors.append(f"schema: expected {SCHEMA_VERSION}, got {report['schema']!r}")
    if report["command"] not in COMMANDS:
        errors.append(f"command: expected one of {', '.join(COMMANDS)}")
    errors += _missing("checked", report["checked"], _CHECKED_KEYS)
    findings = report["findings"]
    if not isinstance(findings, list):
        return [*errors, "findings: expected a list"]
    for index, finding in enumerate(findings):
        errors += _finding_errors(index, finding)
    return errors
