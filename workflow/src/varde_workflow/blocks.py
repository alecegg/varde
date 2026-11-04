"""Operations on managed instruction blocks."""

from __future__ import annotations

from pathlib import Path

START_MARKER = b"<!-- varde:start -->"
END_MARKER = b"<!-- varde:end -->"
LEGACY_TOZ_MARKER = b"<!-- varde-toz:start -->"


def block_ranges(content: bytes) -> list[tuple[int, int]]:
    """Return byte ranges containing paired managed markers."""
    ranges = []
    cursor = 0
    while (start := content.find(START_MARKER, cursor)) >= 0:
        body_start = start + len(START_MARKER)
        end = content.find(END_MARKER, body_start)
        if end < 0:
            break
        block_end = end + len(END_MARKER)
        ranges.append((start, block_end))
        cursor = block_end
    return ranges


def install_block(existing: bytes, block: bytes) -> bytes:
    ranges = block_ranges(existing)
    if not ranges:
        if not existing:
            return block + b"\n"
        return existing + b"\n\n" + block + b"\n"
    output = bytearray()
    cursor = 0
    for index, (start, end) in enumerate(ranges):
        output.extend(existing[cursor:start])
        if index == 0:
            output.extend(block)
        cursor = end
    output.extend(existing[cursor:])
    return bytes(output)


def remove_blocks(existing: bytes) -> bytes:
    ranges = block_ranges(existing)
    if not ranges:
        return existing
    if len(ranges) == 1:
        start, end = ranges[0]
        trailing = existing[end:]
        if start == 0 and trailing == b"\n":
            return b""
        if (
            start >= 2
            and existing[start - 2 : start] == b"\n\n"
            and trailing in (b"", b"\n")
        ):
            return existing[: start - 2]
    output = bytearray()
    cursor = 0
    for start, end in ranges:
        output.extend(existing[cursor:start])
        cursor = end
    output.extend(existing[cursor:])
    return bytes(output)


def has_managed_block(path: Path) -> bool:
    """Whether a readable file contains a paired managed block."""
    try:
        return bool(block_ranges(path.read_bytes()))
    except OSError:
        return False
