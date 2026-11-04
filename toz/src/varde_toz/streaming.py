"""Bounded-input helpers used by capture callers."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from typing import BinaryIO

from .chunk import strip_ansi
from .redact_toz import redact_configured


def spool(source: BinaryIO) -> tuple[BinaryIO, int]:
    target = tempfile.TemporaryFile(mode="w+b")
    size = 0
    while block := source.read(256 * 1024):
        target.write(block)
        size += len(block)
    target.seek(0)
    return target, size


def normalize_and_redact(source: BinaryIO, target: BinaryIO, config: dict) -> int:
    """Normalize and redact a stream with bounded carry across input blocks."""
    carry = ""
    redactions = 0
    in_pem = False
    while True:
        raw = source.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("streamed capture line exceeds 1 MiB; capture rolled back")
        if not raw:
            break
        text = strip_ansi(raw.decode("utf-8", "replace")).replace("\r\n", "\n")
        if config["builtin"]:
            begins = "-----BEGIN " in text and "PRIVATE KEY-----" in text
            ends = "-----END " in text and "PRIVATE KEY-----" in text
            if in_pem or begins:
                if not in_pem:
                    carry += "[redacted:pem]\n"
                    redactions += 1
                in_pem = not ends
                continue
        carry += text
        if len(carry.encode()) > 2 * 1024 * 1024:
            safe_end = carry.rfind("\n", 0, len(carry) - 1024 * 1024)
            if safe_end > 0:
                redacted, count = redact_configured(carry[: safe_end + 1], config)
                target.write(redacted.encode())
                redactions += count
                carry = carry[safe_end + 1 :]
    if carry:
        text, count = redact_configured(carry, config)
        target.write(text.encode())
        redactions += count
    target.flush()
    return redactions


def line_blocks(
    source: BinaryIO,
    *,
    max_lines: int = 80,
    max_bytes: int = 256 * 1024,
    max_line_bytes: int = 1024 * 1024,
) -> Iterator[tuple[int, list[str]]]:
    """Yield fixed-size normalized text blocks with their zero-based line offsets."""
    block: list[str] = []
    block_bytes = 0
    line_number = 0
    while raw := source.readline(max_line_bytes + 1):
        if len(raw) > max_line_bytes:
            raise ValueError("streamed capture line exceeds 1 MiB; capture rolled back")
        block.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
        line_number += 1
        block_bytes += len(raw)
        if len(block) >= max_lines or block_bytes >= max_bytes:
            yield line_number - len(block), block
            block, block_bytes = [], 0
    if block:
        yield line_number - len(block), block
