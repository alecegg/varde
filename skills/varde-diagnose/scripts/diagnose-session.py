#!/usr/bin/env python3
"""Produce a bounded, line-cited diagnostic report for one transcript."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


EVENT_FIELD = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\S+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze one current-session transcript without mutating source."
    )
    parser.add_argument(
        "--transcript",
        help="line-oriented transcript path; defaults to VARDE_CURRENT_SESSION_TRANSCRIPT",
    )
    parser.add_argument("--report", required=True, help="Markdown report destination")
    parser.add_argument(
        "--source",
        choices=("current", "historical"),
        default="current",
        help="transcript source mode",
    )
    parser.add_argument("--session-id", help="historical session identifier")
    parser.add_argument(
        "--historical-consent",
        action="store_true",
        help="authorize one historical read in this process",
    )
    parser.add_argument(
        "--export-dir", help="optional scrubbed export bundle destination"
    )
    parser.add_argument(
        "--export-consent",
        action="store_true",
        help="authorize one export in this process",
    )
    parser.add_argument(
        "--redact-pattern",
        action="append",
        default=[],
        help="literal sensitive pattern to replace in exports; repeatable",
    )
    return parser.parse_args()


def fields_for(line: str) -> dict[str, str]:
    return {match.group("key"): match.group("value") for match in EVENT_FIELD.finditer(line)}


def event_signature(line: str) -> str:
    fields = fields_for(line)
    fields.pop("timestamp", None)
    return " ".join(f"{key}={fields[key]}" for key in sorted(fields))


def read_transcript(transcript: str | None) -> tuple[str | None, list[str], str | None]:
    source = transcript or os.environ.get("VARDE_CURRENT_SESSION_TRANSCRIPT")
    if not source:
        return None, [], "current session transcript path is unavailable"

    path = Path(source)
    if not path.is_file():
        return source, [], f"transcript source is unavailable: {source}"

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return source, [], f"transcript source could not be read: {error}"
    return source, lines, None


def collect_findings(lines: list[str]) -> list[dict[str, object]]:
    categories: dict[str, dict[str, object]] = {}
    seen_signatures: dict[str, list[int]] = defaultdict(list)

    for number, line in enumerate(lines, start=1):
        fields = fields_for(line)
        signature = event_signature(line)
        if signature:
            seen_signatures[signature].append(number)

        if fields.get("request") in {"bug", "regression"} and fields.get("route") == "generic":
            finding = categories.setdefault(
                "routing",
                {
                    "severity": "high",
                    "summary": "Routing sent a bug or regression through the generic route.",
                    "recommendation": "Enter the debugging path before implementation.",
                    "lines": [],
                },
            )
            finding["lines"].append(number)  # type: ignore[union-attr]

        if fields.get("plan") in {"deviation", "deviated"}:
            finding = categories.setdefault(
                "plan",
                {
                    "severity": "medium",
                    "summary": "Plan deviation is recorded in the transcript.",
                    "recommendation": "Record the deviation before continuing the workflow.",
                    "lines": [],
                },
            )
            finding["lines"].append(number)  # type: ignore[union-attr]

        if fields.get("evidence") in {"missing", "failed", "unavailable"}:
            finding = categories.setdefault(
                "evidence",
                {
                    "severity": "high",
                    "summary": "Evidence is missing or unusable for a workflow event.",
                    "recommendation": "Capture the missing evidence before claiming completion.",
                    "lines": [],
                },
            )
            finding["lines"].append(number)  # type: ignore[union-attr]

    for signature, numbers in seen_signatures.items():
        if len(numbers) < 2:
            continue
        finding = categories.setdefault(
            "repeated",
            {
                "severity": "medium",
                "summary": "Repeated diagnostic event appears in the transcript.",
                "recommendation": "Check whether the repeated step can be avoided or consolidated.",
                "lines": [],
            },
        )
        finding["lines"].extend(numbers)  # type: ignore[union-attr]
        break

    return [categories[name] for name in ("routing", "plan", "repeated", "evidence") if name in categories]


def render_report(
    source: str,
    source_path: str | None,
    lines: list[str],
    unavailable_reason: str | None,
    findings: list[dict[str, object]],
    extra_limitations: list[str] | None = None,
) -> str:
    extra_limitations = extra_limitations or []
    state = "unavailable" if unavailable_reason else "available"
    report: list[str] = [
        "# Session diagnostic report",
        "",
        "## Capability",
        f"- source: {source}",
        f"- transcript: {state}",
    ]
    if source_path:
        report.append(f"- path: `{source_path}`")
    if unavailable_reason:
        report.extend([f"- limitation: {unavailable_reason}", ""])
        report.extend(["## Findings", "No findings.", ""])
        report.append("## Limitations")
        report.append("- Analysis stopped because transcript access was unavailable.")
        report.extend(f"- {limitation}" for limitation in extra_limitations)
        return "\n".join(report) + "\n"

    report.extend(["", "## Timeline"])
    for number, line in enumerate(lines, start=1):
        report.append(f"- Line {number}: `{line}`")

    report.extend(["", "## Findings"])
    if not findings:
        report.append("No findings.")
    else:
        for finding in findings:
            lines_for_finding = finding["lines"]
            report.extend(
                [
                    f"### {finding['summary'].split('.', 1)[0].lower()} ({finding['severity']})",
                    f"- Summary: {finding['summary']}",
                    "- Evidence: "
                    + "; ".join(f"transcript line {number}" for number in lines_for_finding),
                    f"- Recommendation: {finding['recommendation']}",
                    "",
                ]
            )

    report.extend(
        [
            "## Limitations",
            "- Findings are heuristic and depend on transcript event fields.",
            "- Diagnostics is analytical and does not edit skills or production source.",
        ]
    )
    report.extend(f"- {limitation}" for limitation in extra_limitations)
    return "\n".join(report) + "\n"


def write_report(destination: str, content: str) -> None:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def redact_text(content: str, patterns: list[str]) -> str:
    for pattern in patterns:
        if pattern:
            content = content.replace(pattern, "[REDACTED]")
    return content


def write_export(
    destination: str,
    transcript_path: str,
    lines: list[str],
    report: str,
    patterns: list[str],
) -> None:
    export_dir = Path(destination)
    export_dir.mkdir(parents=True, exist_ok=True)
    write_report(str(export_dir / "report.md"), redact_text(report, patterns))
    write_report(
        str(export_dir / "transcript.log"),
        redact_text("\n".join(lines) + "\n", patterns),
    )
    write_report(
        str(export_dir / "NOTICE.md"),
        "# Diagnostic export notice\n\n"
        f"- Source: `{transcript_path}`\n"
        "- Residual risk: configured sensitive patterns are redacted, "
        "but complete secret removal is not guaranteed.\n",
    )


def main() -> int:
    args = parse_args()
    if args.source == "historical" and not args.session_id:
        write_report(
            args.report,
            "# Session diagnostic report\n\n"
            "## Capability\n"
            "- source: historical\n"
            "- transcript: unavailable\n"
            "- limitation: a historical session identifier is required\n\n"
            "## Findings\n"
            "No findings.\n",
        )
        return 2

    if args.source == "historical" and not args.transcript:
        write_report(
            args.report,
            "# Session diagnostic report\n\n"
            "## Capability\n"
            "- source: historical\n"
            "- transcript: unavailable\n"
            "- limitation: historical transcript path is required\n\n"
            "## Findings\n"
            "No findings.\n",
        )
        return 2

    if args.source == "historical" and not args.historical_consent:
        write_report(
            args.report,
            "# Session diagnostic report\n\n"
            "## Capability\n"
            "- source: historical\n"
            "- transcript: unavailable\n"
            "- limitation: explicit historical consent is required; "
            "consent expired after each diagnostic run\n\n"
            "## Findings\n"
            "No findings.\n",
        )
        return 2

    source_path, lines, unavailable_reason = read_transcript(args.transcript)
    findings = collect_findings(lines) if not unavailable_reason else []
    limitations: list[str] = []
    if args.export_dir and not args.export_consent:
        limitations.append("Export withheld because separate export consent was absent.")
    report = render_report(
        args.source,
        source_path,
        lines,
        unavailable_reason,
        findings,
        limitations,
    )
    write_report(args.report, report)

    if args.export_dir and args.export_consent and not unavailable_reason and source_path:
        write_export(args.export_dir, source_path, lines, report, args.redact_pattern)
    return 0


if __name__ == "__main__":
    sys.exit(main())
