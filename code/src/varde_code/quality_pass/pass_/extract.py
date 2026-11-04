"""Per-file L1 extraction and the parsing process pool."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor

from varde_code.extract.entity import extract_file
from varde_code.model import EntityKind
from varde_code.quality_pass.facts import extract_facts

from .index_read import IndexedFile
from .keys import content_digest

LOW_PRIORITY_INCREMENT = 5
ExtractItem = tuple[IndexedFile, bytes]


def extract_record(indexed: IndexedFile, raw: bytes) -> dict:
    """Build one facts-2 record from bytes already read and hashed once."""
    text = raw.decode("utf-8-sig", errors="replace")
    record = extract_facts(raw, indexed.language, indexed.path)
    record["content_hash"] = content_digest(raw)
    record["imports"] = import_specs(str(indexed.absolute), text, indexed.language)
    return record


def import_specs(absolute: str, text: str, language: str) -> list[dict]:
    """Return this file's import specifiers sorted by line then specifier.

    The pass-internal ``imports`` field lets the resolver hook restrict
    cross-file edges to imported modules without re-parsing in ``prepare``.
    The extraction is the same language entity pass the fast index uses, so no
    per-language node shape is guessed here.
    Go grouped imports are reported per specifier, without their surrounding
    ``import (`` declaration; Rust ``mod m;`` declarations are also imports.
    """
    extracted = extract_file(absolute, text, language)
    source = text.encode("utf-8")
    found: dict[tuple[int, str], str] = {}
    for entity in extracted.entities:
        if entity.kind != EntityKind.IMPORT or not entity.name:
            continue
        start = max(entity.span.start_byte, 0)
        end = min(entity.span.end_byte, len(source))
        statement = source[start:end].decode("utf-8", errors="replace").strip()[:1000]
        found.setdefault((entity.span.start_line, entity.name), statement)
    return [
        {"line": line, "module": module, "text": statement}
        for (line, module), statement in sorted(found.items())
    ]


def extract_records(
    items: Sequence[ExtractItem], *, workers: int
) -> Iterator[tuple[str, dict]]:
    """Yield ``(path, record)`` in input order, parsed by a process pool."""
    if not items:
        return
    if workers <= 1:
        for item in items:
            yield _extract_job(item)
        return
    try:
        pool = ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority)
    except (OSError, ValueError) as exc:
        print(
            f"quality pass: process pool unavailable, extracting serially: {exc}",
            file=sys.stderr,
        )
        for item in items:
            yield _extract_job(item)
        return
    with pool:
        yield from pool.map(_extract_job, items)


def _extract_job(item: ExtractItem) -> tuple[str, dict]:
    indexed, raw = item
    return indexed.path, extract_record(indexed, raw)


def _lower_priority() -> None:
    with contextlib.suppress(OSError):  # pragma: no cover - platform dependent
        os.nice(LOW_PRIORITY_INCREMENT)
