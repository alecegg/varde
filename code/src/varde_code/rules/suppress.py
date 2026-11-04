"""Inline suppression comments, recognized only inside tree-sitter comments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from varde_code.parse import language_for_path, parse_source
from varde_code.rules.finding import Finding

FILE_MARKER = "varde-ignore-file"
NEXT_LINE_MARKER = "varde-ignore-next-line"


@dataclass(frozen=True)
class Suppression:
    line: int
    comment_line: int
    rule_ids: list[str]
    reason: str | None

    def matches(self, line: int, rule_id: str) -> bool:
        return (self.line in (0, line)) and (
            not self.rule_ids or rule_id in self.rule_ids
        )


@dataclass(frozen=True)
class StaleSuppression:
    file: str
    comment_line: int
    rule_ids: list[str]
    reason: str | None


def _tail(rest: str) -> tuple[list[str], str | None]:
    targets, separator, reason = rest.partition("--")
    ids = list(targets.replace(",", " ").split())
    reason = reason.strip() if separator else ""
    return ids, reason or None


def parse_suppressions(source: str, path: str | Path) -> list[Suppression]:
    language = language_for_path(path)
    if language is None:
        return []
    root = parse_source(language, source).root
    ranges: list[tuple[int, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if "comment" in node.type:
            ranges.append((node.start_byte, node.end_byte))
        stack.extend(node.children)
    output = []
    offset = 0
    lines = source.split("\n")
    for index, line in enumerate(lines):
        if index == len(lines) - 1 and line == "" and source.endswith("\n"):
            break
        number = index + 1
        marker = (
            FILE_MARKER
            if FILE_MARKER in line
            else NEXT_LINE_MARKER
            if NEXT_LINE_MARKER in line
            else None
        )
        if marker:
            marker_index = line.index(marker)
            pos = offset + len(line[:marker_index].encode("utf-8"))
            if any(start <= pos < end for start, end in ranges):
                ids, reason = _tail(line[line.index(marker) + len(marker) :])
                output.append(
                    Suppression(
                        0 if marker == FILE_MARKER else number + 1, number, ids, reason
                    )
                )
        offset += len(line.encode("utf-8")) + (index < len(lines) - 1)
    return output


def filter_findings(
    findings: list[Finding], repo_root: str | Path
) -> tuple[list[Finding], list[StaleSuppression]]:
    root = Path(os.path.abspath(repo_root))
    by_file: dict[str, list[tuple[int, Finding]]] = {}
    for index, finding in enumerate(findings):
        by_file.setdefault(finding.location.file, []).append((index, finding))
    keep = [True] * len(findings)
    stale: list[StaleSuppression] = []
    for file, indexed_group in by_file.items():
        path = Path(file)
        if not path.is_absolute():
            absolute = Path(os.path.abspath(path))
            path = absolute if absolute.is_relative_to(root) else root / path
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        directives = parse_suppressions(source, path)
        used: set[int] = set()
        for index, finding in indexed_group:
            match = next(
                (
                    i
                    for i, directive in enumerate(directives)
                    if directive.matches(
                        finding.location.span.start_line, finding.rule_id
                    )
                ),
                None,
            )
            if match is None:
                continue
            used.add(match)
            keep[index] = False
        stale.extend(
            StaleSuppression(file, item.comment_line, item.rule_ids, item.reason)
            for i, item in enumerate(directives)
            if i not in used
        )
    return [finding for index, finding in enumerate(findings) if keep[index]], stale
