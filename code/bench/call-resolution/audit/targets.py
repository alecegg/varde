"""Canonical target keys for call-audit ground-truth target ids.

The dev groups label their targets with one of three id grammars:

- python-ts: ``<file>::<qualified-name>@<line>``
  (``django/apps/config.py::AppConfig.create@100``)
- go-rust and cpp: ``<file>:<line>:<name>``
  (``rayon-core/src/lib.rs:239:new``)
- java-csharp: ``<file>::<qualified-signature>``, no line
  (``...AiPreferences.java::org.jabref...AiPreferences.customizeExpertSettingsProperty()``)

Parsing yields a :class:`TargetKey` holding the repo-relative file, the
*declared* name (the last name segment, with generic arguments, parameter
lists and constructor markers removed), and the target's start line when the
grammar carries one.

Match rule: two keys match when their files and names are equal, and when both
carry a line those lines are equal. An ``<anonymous>`` truth name whose key
carries a line
matches any measured name in the same file and line. Line-less grammars
(java-csharp) therefore collapse overloads that share a file and a name. The
measured side always carries the index entity's start line, so line-bearing
grammars reject a target declared on a different line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AT_LINE = "qualified-at-line"
FILE_LINE_NAME = "file-line-name"
MEMBER_SIGNATURE = "qualified-member-signature"

GRAMMAR_BY_LANGUAGE = {
    "python": AT_LINE,
    "typescript": AT_LINE,
    "go": FILE_LINE_NAME,
    "rust": FILE_LINE_NAME,
    "cpp": FILE_LINE_NAME,
    "java": MEMBER_SIGNATURE,
    "csharp": MEMBER_SIGNATURE,
}

_FILE_LINE_NAME = re.compile(
    r"^(?P<file>[^:]+):(?P<line>[0-9]+):(?P<name>.+)$",
    re.DOTALL,
)


@dataclass(frozen=True)
class TargetKey:
    """Comparable identity of one call target."""

    file: str
    name: str
    line: int | None = None


def target_keys_match(measured: TargetKey, truth: TargetKey) -> bool:
    """Return whether a measured target satisfies the ground-truth target."""
    if measured.file != truth.file:
        return False
    if truth.name == "<anonymous>" and truth.line is not None:
        return measured.line == truth.line
    if truth.name != measured.name:
        return False
    return truth.line is None or measured.line == truth.line


def parse_target_id(language: str, target_id: str) -> TargetKey:
    """Parse a ground-truth target id for ``language`` into a target key."""
    try:
        grammar = GRAMMAR_BY_LANGUAGE[language]
    except KeyError:
        raise ValueError(f"no target-id grammar for language {language!r}") from None
    if grammar == AT_LINE:
        return _parse_at_line(target_id)
    if grammar == FILE_LINE_NAME:
        return _parse_file_line_name(target_id)
    return _parse_member_signature(target_id)


def _parse_at_line(target_id: str) -> TargetKey:
    qualified_part, separator, line_text = target_id.rpartition("@")
    if not separator or not line_text.isdigit():
        raise ValueError(f"target id lacks a trailing @<line>: {target_id!r}")
    file, separator, qualified = qualified_part.partition("::")
    if not separator or not file or not qualified:
        raise ValueError(f"target id lacks <file>::<name>: {target_id!r}")
    name = qualified.rsplit(".", 1)[-1]
    return _target_key(file, name, int(line_text))


def _parse_file_line_name(target_id: str) -> TargetKey:
    match = _FILE_LINE_NAME.match(target_id)
    if match is None:
        raise ValueError(f"target id lacks <file>:<line>:<name>: {target_id!r}")
    return _target_key(match["file"], match["name"], int(match["line"]))


def _parse_member_signature(target_id: str) -> TargetKey:
    file, separator, qualified = target_id.partition("::")
    if not separator or not file or not qualified:
        raise ValueError(f"target id lacks <file>::<name>: {target_id!r}")
    declared = _strip_generic_arguments(qualified.split("(", 1)[0])
    name = declared.rsplit(".", 1)[-1]
    if name in {"<init>", "<clinit>"}:
        name = _enclosing_type_name(declared, target_id)
    return _target_key(file, name, None)


def _strip_generic_arguments(declared: str) -> str:
    parts = []
    depth = 0
    position = 0
    while position < len(declared):
        constructor = next(
            (
                marker
                for marker in ("<init>", "<clinit>")
                if declared.startswith(marker, position)
            ),
            None,
        )
        if constructor is not None and depth == 0:
            parts.append(constructor)
            position += len(constructor)
            continue
        character = declared[position]
        if character == "<":
            depth += 1
        elif character == ">" and depth:
            depth -= 1
        elif depth == 0:
            parts.append(character)
        position += 1
    return "".join(parts)


def _enclosing_type_name(declared: str, target_id: str) -> str:
    segments = declared.rsplit(".", 2)
    if len(segments) < 3 or not segments[-2]:
        raise ValueError(
            f"constructor target id lacks an enclosing type: {target_id!r}"
        )
    return segments[-2]


def _target_key(file: str, name: str, line: int | None) -> TargetKey:
    if not file or not name:
        raise ValueError(
            f"target id has an empty file or name: file={file!r} name={name!r}"
        )
    if line is not None and line < 1:
        raise ValueError(f"target id has a non-positive line: {line}")
    return TargetKey(file=file, name=name, line=line)
