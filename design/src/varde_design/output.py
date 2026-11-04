"""Text and JSON rendering of a report dict. Pure."""

from __future__ import annotations

import json

SNIPPET_CHARS = 100


def render_json(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2) + "\n"


def _where(finding: dict[str, object]) -> str:
    line = finding["line"]
    return f"{finding['file']}:{line}" if line else str(finding["file"])


def _finding_lines(finding: dict[str, object]) -> list[str]:
    head = (
        f"{_where(finding)} {finding['severity']} {finding['id']} {finding['message']}"
    )
    snippet = str(finding["snippet"]).strip()[:SNIPPET_CHARS]
    return [head, f"    {snippet}"] if snippet else [head]


def _checked_lines(checked: dict[str, object]) -> list[str]:
    tiers = ", ".join(checked["tiers"])  # type: ignore[arg-type]
    widths = ",".join(str(w) for w in checked["widths"])  # type: ignore[attr-defined]
    summary = (
        f"checked: tiers {tiers}; settings {checked['settings_source']}; "
        f"{checked['elements']} elements"
    )
    lines = [summary + (f"; widths {widths}" if widths else "")]
    truncated = checked["truncated"]
    if truncated:
        lines.append(f"truncated: {truncated['shown']} of {truncated['total']}")  # type: ignore[index]
    lines += [f"note: {item}" for item in checked.get("notes", [])]  # type: ignore[attr-defined]
    lines += [f"not run: {item}" for item in checked["not_run"]]  # type: ignore[union-attr]
    return lines


def _ignore_lines(data: dict[str, object]) -> list[str]:
    echoes = data.get("ignores") or []
    return [
        f"ignore {e['status']}: {e['file']}:{e['line']} {e['id']} reason: {e['reason']}"  # type: ignore[index]
        for e in echoes  # type: ignore[union-attr]
    ]


def render_check_text(report: dict[str, object]) -> str:
    findings: list[dict[str, object]] = report["findings"]  # type: ignore[assignment]
    lines: list[str] = []
    for finding in findings:
        lines += _finding_lines(finding)
    fails = sum(1 for f in findings if f["severity"] == "fail")
    lines.append(f"{len(findings)} findings ({fails} fail)")
    lines += _ignore_lines(report["data"])  # type: ignore[arg-type]
    lines += _checked_lines(report["checked"])  # type: ignore[arg-type]
    return "\n".join(lines) + "\n"


def render_tokens_text(report: dict[str, object], cap: int = 200) -> str:
    data: dict[str, object] = report["data"]  # type: ignore[assignment]
    tokens: list[dict[str, object]] = data["tokens"]  # type: ignore[assignment]
    lines = [f"{t['name']}: {t['resolved']}" for t in tokens[:cap]]
    if len(tokens) > cap:
        lines.append(f"(+{len(tokens) - cap} more; use --json)")
    if not tokens:
        lines.append("no tokens found")
    lines += _checked_lines(report["checked"])  # type: ignore[arg-type]
    return "\n".join(lines) + "\n"
