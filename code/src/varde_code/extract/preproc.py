"""Scan C-family and Haskell CPP conditional regions."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TypedDict

from varde_code.model import Entity, EntityKind, Span

_DIRECTIVE = re.compile(
    r"^\s*#\s*(if|ifdef|ifndef|elif|elseif|else|endif|define)\b(.*)$"
)


class _Conditional(TypedDict):
    start: int
    line: int
    branch: int | None
    skip: bool


def scan(
    source: str, file_id: int = 0, enabled: bool = True, haskell_cpp: bool = False
) -> list[Entity]:
    if not enabled or (haskell_cpp and "{-# LANGUAGE CPP #-}" not in source):
        return []
    lines = []
    offset = 0
    for line_number, raw in enumerate(source.splitlines(keepends=True)):
        match = _DIRECTIVE.match(raw)
        if match:
            lines.append(
                (
                    line_number,
                    offset + len(raw) - len(raw.lstrip()),
                    offset + len(raw.rstrip("\r\n")),
                    match.group(1),
                    match.group(2).strip(),
                )
            )
        offset += len(raw)
    guard_name = None
    if lines and lines[0][3] == "ifndef":
        guard_name = lines[0][4]
        if not any(
            name == "define" and arg.split(maxsplit=1)[:1] == [guard_name]
            for _, _, _, name, arg in lines[1:]
        ):
            guard_name = None
    stack: list[_Conditional] = []
    result = []
    for line, start, end, name, arg in lines:
        if name in {"if", "ifdef", "ifndef"}:
            stack.append(
                {
                    "start": start,
                    "line": line,
                    "branch": None,
                    "skip": name == "ifndef"
                    and line == lines[0][0]
                    and arg == guard_name,
                }
            )
        elif name in {"elif", "elseif", "else"} and stack:
            open_region = stack[-1]
            branch = open_region["branch"]
            if branch is not None:
                result.append(_entity(source, file_id, "preproc_branch", branch, start))
            open_region["branch"] = start
        elif name == "endif" and stack:
            opened = stack.pop()
            if opened["branch"] is not None:
                result.append(
                    _entity(source, file_id, "preproc_branch", opened["branch"], start)
                )
            if not opened["skip"]:
                result.append(
                    _entity(source, file_id, "preproc_if", opened["start"], end)
                )
    return sorted(
        result, key=lambda entity: (entity.span.start_byte, entity.span.end_byte)
    )


def attribute_top_level_regions(markers: list[Entity], entities: list[Entity]) -> None:
    originals = markers.copy()
    callables = [entity for entity in entities if entity.kind == EntityKind.FUNCTION]
    for marker in originals:
        if marker.name not in {"preproc_if", "preproc_branch"}:
            continue
        for callable_entity in callables:
            if not _contains(marker.span, callable_entity.span):
                continue
            nested = any(
                parent is not callable_entity
                and parent.span != callable_entity.span
                and _contains(marker.span, parent.span)
                and _contains(parent.span, callable_entity.span)
                for parent in callables
            )
            if nested:
                continue
            markers.append(
                replace(
                    marker,
                    span=callable_entity.span,
                    enclosing_function=callable_entity.name,
                    owner_type=callable_entity.owner_type,
                )
            )


def _contains(outer: Span, inner: Span) -> bool:
    return outer.start_byte <= inner.start_byte and outer.end_byte >= inner.end_byte


def _entity(source: str, file_id: int, name: str, start: int, end: int) -> Entity:
    start_point = _point(source, start)
    end_point = _point(source, end)
    return Entity(
        EntityKind.CONTROL_FLOW,
        name,
        file_id,
        Span(start, end, start_point[0], start_point[1], end_point[0], end_point[1]),
    )


def _point(source: str, offset: int) -> tuple[int, int]:
    prefix = source[:offset]
    return prefix.count("\n") + 1, len(prefix.rsplit("\n", 1)[-1].encode("utf-8"))
