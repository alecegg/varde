"""Rewrite-template substitution and per-file rewrite planning."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class TemplateToken:
    """A named template capture and its character offsets in the template."""

    start: int
    end: int
    variadic: bool
    name: str


def template_tokens(template: str) -> Iterator[TemplateToken]:
    """Yield named ``$VAR`` and ``$$$VAR`` tokens in order."""
    i = 0
    while i < len(template):
        if template.startswith("$$$", i):
            sigil_len, variadic = 3, True
        elif template[i] == "$":
            sigil_len, variadic = 1, False
        else:
            i += 1
            continue

        name_start = i + sigil_len
        name_end = name_start
        while name_end < len(template) and (
            template[name_end].isascii()
            and (template[name_end].isalnum() or template[name_end] == "_")
        ):
            name_end += 1
        if name_end == name_start:
            i += sigil_len
            continue
        yield TemplateToken(i, name_end, variadic, template[name_start:name_end])
        i = name_end


def substitute(template: str, captures: Any) -> str:
    """Replace named captures with their matched text."""
    return substitute_with_source(template, captures)


def substitute_with_source(
    template: str, captures: Any, source: str | None = None
) -> str:
    """Substitute captures, preserving source separators for valid arrays."""
    capture_map = captures if isinstance(captures, dict) else {}
    out: list[str] = []
    cursor = 0
    for token in template_tokens(template):
        out.append(template[cursor : token.start])
        if token.name in capture_map:
            out.append(_capture_text(capture_map[token.name], source))
        else:
            out.append(template[token.start : token.end])
        cursor = token.end
    out.append(template[cursor:])
    return "".join(out)


def _capture_text(value: Any, source: str | None) -> str:
    if isinstance(value, list):
        if source is not None:
            separated = _capture_array_with_separators(value, source)
            if separated is not None:
                return separated
        return "".join(text for node in value if (text := _node_text(node)) is not None)
    text = _node_text(value)
    return text if text is not None else ""


def _capture_array_with_separators(nodes: list[Any], source: str) -> str | None:
    texts = [_node_text(node) for node in nodes]
    spans = [_node_span(node) for node in nodes]
    if any(text is None for text in texts) or any(span is None for span in spans):
        return None

    source_bytes = source.encode("utf-8")
    valid_spans = [span for span in spans if span is not None]
    if any(
        start > end or _decode_utf8_slice(source_bytes, start, end) is None
        for start, end in valid_spans
    ):
        return None
    if any(left[1] > right[0] for left, right in itertools.pairwise(valid_spans)):
        return None

    out: list[str] = []
    for index, text in enumerate(texts):
        out.append(text or "")
        if index + 1 < len(valid_spans):
            separator = _decode_utf8_slice(
                source_bytes, valid_spans[index][1], valid_spans[index + 1][0]
            )
            if separator is None:
                return None
            out.append(separator)
    return "".join(out)


def _decode_utf8_slice(source: bytes, start: int, end: int) -> str | None:
    try:
        return (
            source[start:end].decode("utf-8")
            if 0 <= start <= end <= len(source)
            else None
        )
    except UnicodeDecodeError:
        return None


def _node_text(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None
    text = node.get("text")
    return text if isinstance(text, str) else None


def _node_span(node: Any) -> tuple[int, int] | None:
    if not isinstance(node, dict) or not isinstance(node.get("span"), dict):
        return None
    span = node["span"]
    start, end = span.get("start_byte"), span.get("end_byte")
    if not _is_unsigned_int(start) or not _is_unsigned_int(end):
        return None
    return start, end


def _is_unsigned_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class RewriteTarget:
    start_byte: int
    end_byte: int
    replacement: str


class RewriteStatus(StrEnum):
    APPLIED = "applied"
    SKIPPED_DIRTY = "skipped-dirty"
    SKIPPED_OVERLAP = "skipped-overlap"
    SKIPPED_CONFLICT = "skipped-conflict"


class RewritePlan(StrEnum):
    APPLY = "apply"
    SKIPPED_OVERLAP = "skipped-overlap"


def plan_file_rewrites(targets: list[RewriteTarget]) -> list[RewritePlan]:
    """Sort by span and mark overlapping later targets as skipped."""
    order = sorted(
        range(len(targets)),
        key=lambda index: (targets[index].start_byte, targets[index].end_byte),
    )
    plans = [RewritePlan.SKIPPED_OVERLAP] * len(targets)
    last_end = 0
    for index in order:
        target = targets[index]
        if target.start_byte >= last_end:
            plans[index] = RewritePlan.APPLY
            last_end = max(last_end, target.end_byte)
    return plans
