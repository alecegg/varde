"""The `design-ignore` comment grammar: parse comments, apply them to findings. Pure.

Grammar (inside any comment style; the text after reason: runs to the comment
end or the end of the line):

    design-ignore <id>[, <id>...] reason: <text>

An ignore covers findings on its own line and on the next line. A fail finding
is never waived (it stays in the findings and the echo says refused). A reason
under MIN_REASON_CHARS, an unknown id or a missing part makes the comment a
finding (id IGN) that waives nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .registry import RULES_BY_ID
from .report import Finding

MIN_REASON_CHARS = 24
META_ID = "IGN"

_MARKER = re.compile(r"design-ignore\b(?P<rest>.*)", re.IGNORECASE)
_REASON = re.compile(r"\breason\s*:\s*(?P<text>.*)", re.IGNORECASE)
_COMMENT_END = re.compile(r"\*/|-->")
_ID = re.compile(r"[A-Za-z]+\d+")


@dataclass(frozen=True)
class Ignore:
    file: str
    line: int
    ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class IgnoreEcho:
    """One ignore as reported: status is applied, unused or refused."""

    file: str
    line: int
    id: str
    reason: str
    status: str


def _bad(file: str, line: int, snippet: str, message: str) -> Finding:
    return Finding(META_ID, "warn", "static", file, message, line=line, snippet=snippet)


def _split_ids(head: str) -> list[str]:
    return (
        [part.strip().upper() for part in head.strip().split(",")]
        if head.strip()
        else []
    )


def _parse_comment(file: str, line: int, rest: str, snippet: str) -> Ignore | Finding:
    reason_match = _REASON.search(rest)
    if reason_match is None:
        return _bad(file, line, snippet, "design-ignore needs 'reason: <text>'")
    ids = _split_ids(rest[: reason_match.start()])
    reason = _COMMENT_END.split(reason_match.group("text"))[0].strip()
    if not ids or not all(_ID.fullmatch(item) for item in ids):
        return _bad(file, line, snippet, "design-ignore needs rule ids such as S7,S9")
    unknown = [item for item in ids if item not in RULES_BY_ID]
    if unknown:
        message = f"design-ignore names unknown rule id {', '.join(unknown)}"
        return _bad(file, line, snippet, message)
    if len(reason) < MIN_REASON_CHARS:
        message = f"design-ignore reason is under {MIN_REASON_CHARS} characters"
        return _bad(file, line, snippet, message)
    return Ignore(file, line, tuple(dict.fromkeys(ids)), reason)


def parse_ignores(text: str, file: str) -> tuple[list[Ignore], list[Finding]]:
    """Valid ignores and the findings for malformed ones, in line order."""
    ignores: list[Ignore] = []
    bad: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = _MARKER.search(line)
        if match is None:
            continue
        parsed = _parse_comment(file, number, match.group("rest"), line.strip())
        if isinstance(parsed, Finding):
            bad.append(parsed)
        else:
            ignores.append(parsed)
    return ignores, bad


def _covers(ignore: Ignore, finding: Finding) -> bool:
    on_line = finding.line in (ignore.line, ignore.line + 1)
    return ignore.file == finding.file and on_line and finding.id in ignore.ids


def apply_ignores(
    findings: list[Finding],
    ignores: list[Ignore],
    config_ids: tuple[str, ...] = (),
) -> tuple[list[Finding], list[IgnoreEcho]]:
    """Findings left after waivers, and one echo per (ignore, rule id).

    config_ids waive those rules everywhere (the config `ignore` entry); a fail
    finding is kept either way.
    """
    waived: set[int] = set()
    echoes: list[IgnoreEcho] = []
    for ignore in ignores:
        for rule_id in ignore.ids:
            hits = [
                i
                for i, f in enumerate(findings)
                if _covers(ignore, f) and f.id == rule_id
            ]
            status = _status(findings, hits)
            waived.update(i for i in hits if findings[i].severity != "fail")
            echoes.append(
                IgnoreEcho(ignore.file, ignore.line, rule_id, ignore.reason, status)
            )
    waived.update(
        i for i, f in enumerate(findings) if f.id in config_ids and f.severity != "fail"
    )
    kept = [f for i, f in enumerate(findings) if i not in waived]
    return kept, echoes


def _status(findings: list[Finding], hits: list[int]) -> str:
    if not hits:
        return "unused"
    if all(findings[i].severity == "fail" for i in hits):
        return "refused"
    return "applied"
