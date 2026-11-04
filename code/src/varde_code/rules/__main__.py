"""JSON command-line runner for the code rule engine."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from varde_code.model import Entity, EntityKind, ExtractOutput, Span
from varde_code.rules.engine import run_rules
from varde_code.rules.finding import Finding
from varde_code.rules.loader import load_rules
from varde_code.rules.model import Diagnostic
from varde_code.rules.scan_output import build_scan_payload, filter_generated
from varde_code.rules.suppress import filter_findings
from varde_code.seams import ExtractionProvider


class ExtractionJsonProvider:
    """Serve extraction records loaded from a JSON file."""

    def __init__(self, path: str | Path, repo_root: str | Path | None = None):
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        self.data = document.get("data", document)
        self.files = self.data.get("files", [])
        self.entities = self.data.get("entities", [])
        self.repo_root = Path(repo_root).resolve() if repo_root is not None else None

    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        relative = (
            path.resolve().relative_to(self.repo_root).as_posix()
            if self.repo_root
            else path.as_posix()
        )
        entities = []
        for item in self.entities:
            file_id = item.get("file_id")
            if not isinstance(file_id, int) or file_id >= len(self.files):
                continue
            if self.files[file_id] != relative:
                continue
            span = item.get("span", {})
            entities.append(
                Entity(
                    kind=EntityKind[item["kind"].upper()],
                    name=item["name"],
                    file_id=file_id,
                    span=Span(
                        *(
                            int(span.get(key, 0))
                            for key in (
                                "start_byte",
                                "end_byte",
                                "start_line",
                                "start_col",
                                "end_line",
                                "end_col",
                            )
                        )
                    ),
                    enclosing_function=item.get("enclosing_function"),
                    method=item.get("method"),
                    path=item.get("path"),
                    status=item.get("status"),
                    body_shape=item.get("body_shape"),
                    body_minhash=item.get("body_minhash"),
                    is_async=item.get("is_async"),
                    is_test=bool(item.get("is_test", False)),
                    owner_type=item.get("owner_type"),
                )
            )
        return ExtractOutput(entities=entities)


def scan(
    repo_root: str | Path,
    conn: sqlite3.Connection,
    rules: list[Any],
    provider: ExtractionProvider,
    *,
    rule_diagnostics: list[Diagnostic] | None = None,
) -> dict[str, Any]:
    """Run rules with an injectable extraction provider and match the scan JSON
    payload."""
    root = Path(repo_root)
    findings, diagnostics = run_rules(rules, root, conn, provider)
    findings, stale = filter_findings(filter_generated(findings), root)
    records = [
        *(_diagnostic_dict(item) for item in (rule_diagnostics or [])),
        *(_diagnostic_dict(item) for item in diagnostics),
    ]
    return build_scan_payload(findings, records, stale, rules, root)


def _finding_dict(finding: Finding) -> dict[str, Any]:
    return finding.to_dict()


def _diagnostic_dict(item: Diagnostic) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if item.rule_id is not None:
        result["rule_id"] = item.rule_id
    result["file"] = item.file
    result["reason"] = item.reason
    return result


def response_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": payload,
        "meta": {"compact": True, "truncated": False},
        "ok": True,
        "outcome": payload.get("outcome", "success"),
        "schema_version": 1,
    }


def response_exit_code(payload: dict[str, Any]) -> int:
    return 0 if payload.get("gate", {}).get("status") == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m varde_code.rules")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("scan")
    command.add_argument("--json", action="store_true", dest="as_json")
    command.add_argument("--repo-root", required=True, type=Path)
    command.add_argument("--db", required=True, type=Path)
    command.add_argument("--extraction-json", required=True, type=Path)
    args = parser.parse_args(argv)
    rules, rule_diagnostics = load_rules(args.repo_root)
    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as conn:
        payload = scan(
            args.repo_root,
            conn,
            rules,
            ExtractionJsonProvider(args.extraction_json, args.repo_root),
            rule_diagnostics=rule_diagnostics,
        )
    json.dump(
        response_envelope(payload),
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    sys.stdout.write("\n")
    return response_exit_code(payload)


if __name__ == "__main__":
    raise SystemExit(main())
