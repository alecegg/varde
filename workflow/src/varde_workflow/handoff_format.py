"""Pure validation for the nine-section agent handoff format."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

SECTIONS = (
    "Summary",
    "Goal",
    "Context",
    "State",
    "Next",
    "Open",
    "Reading list",
    "Pointers",
    "Do not redo",
)
_HEADER = re.compile(
    r"^(Summary|Goal|Context|State|Next|Open|Reading list|Pointers|Do not redo):"
    r"(?:\s*(.*))?$"
)
_CANDIDATE = re.compile(r"^-\s+(?:\[(global|project|role)\]\s+)?(.+?)\s+—\s+(.+)$")
_TAGGED_BULLET = re.compile(r"^-\s+\[([^]]*)\]")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
_BULLET = re.compile(r"^\s*[-*+]\s+")
_LIMITS = (
    ("State", 5),
    ("Next", 3),
    ("Open", 3),
    ("Reading list", 8),
    ("Do not redo", 5),
)


@dataclass(frozen=True)
class HandoffResult:
    errors: list[str]
    warnings: list[str]
    summary: str
    candidates: list[dict[str, str]]


def _sections(text: str) -> tuple[dict[str, list[str]], list[str], list[str]]:
    sections = {name: [] for name in SECTIONS}
    found: list[str] = []
    errors: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        header = _HEADER.match(line)
        if header:
            section = header.group(1)
            if section is None:
                continue
            current = section
            found.append(section)
            sections[section].append(header.group(2) or "")
        elif current is not None:
            sections[current].append(line)
        elif line.strip():
            errors.append("Summary: content appears before the first section")
            break
    return sections, found, errors


def _order_errors(found: list[str]) -> list[str]:
    errors = []
    for index, section in enumerate(SECTIONS):
        if section not in found:
            errors.append(f"{section}: required section is missing")
        elif found.index(section) != index:
            errors.append(f"{section}: sections are out of order")
        if found.count(section) > 1:
            errors.append(f"{section}: section appears more than once")
    return errors


def _content(sections: dict[str, list[str]]) -> dict[str, str]:
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _summary(content: dict[str, str]) -> tuple[str, list[str]]:
    lines = [line for line in content["Summary"].splitlines() if line.strip()]
    errors = []
    if len(lines) != 1:
        errors.append("Summary: expected one non-empty line")
    summary = lines[0] if lines else ""
    if len(summary) > 120:
        errors.append("Summary: exceeds 120 characters")
    return summary, errors


def _item_lines(value: str, section: str) -> list[str]:
    lines = [line for line in value.splitlines() if line.strip()]
    if section in {"State", "Open", "Do not redo"}:
        return [line for line in lines if _BULLET.match(line)]
    if section == "Next":
        return [line for line in lines if _NUMBERED.match(line)]
    return lines


def _section_limit_errors(content: dict[str, str]) -> list[str]:
    errors = []
    if len(content["Context"].split()) > 250:
        errors.append("Context: exceeds 250 words")
    for section, limit in _LIMITS:
        count = len(_item_lines(content[section], section))
        if count > limit:
            unit = "paths" if section == "Reading list" else "items"
            errors.append(f"{section}: exceeds {limit} {unit}")
    return errors


def _reading_warnings(value: str, path_exists: Callable[[str], bool]) -> list[str]:
    warnings = []
    for line in value.splitlines():
        path = re.sub(r"^[-*+]\s+", "", line.strip()).strip().strip("`")
        if path and not path_exists(path):
            warnings.append(f"Reading list: path does not exist: {path}")
    return warnings


def _candidates(value: str) -> tuple[list[dict[str, str]], list[str]]:
    candidates = []
    errors = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        tagged = _TAGGED_BULLET.match(stripped)
        parsed = _CANDIDATE.match(stripped)
        if tagged and tagged.group(1) not in {"global", "project", "role"}:
            errors.append("Pointers: malformed memory candidate tag")
        elif tagged and not parsed:
            errors.append("Pointers: malformed memory candidate format")
        elif parsed:
            candidates.append(
                {
                    "tag": parsed.group(1) or "project",
                    "text": parsed.group(2),
                    "why": parsed.group(3),
                }
            )
    if len(candidates) > 5:
        errors.append("Pointers: exceeds 5 memory candidates")
    return candidates, errors


def _total_errors(text: str) -> list[str]:
    errors = []
    if len(text.split()) > 700:
        errors.append("Summary: total handoff exceeds 700 words")
    if len(text) > 5000:
        errors.append("Summary: total handoff exceeds 5000 characters")
    return errors


def validate(text: str, path_exists: Callable[[str], bool]) -> HandoffResult:
    """Validate sections and limits; the caller supplies Reading list checks."""
    sections, found, errors = _sections(text)
    content = _content(sections)
    summary, summary_errors = _summary(content)
    candidates, candidate_errors = _candidates(content["Pointers"])
    errors.extend(_order_errors(found))
    errors.extend(summary_errors)
    errors.extend(_section_limit_errors(content))
    errors.extend(candidate_errors)
    errors.extend(_total_errors(text))
    warnings = _reading_warnings(content["Reading list"], path_exists)
    return HandoffResult(errors, warnings, summary, candidates)
