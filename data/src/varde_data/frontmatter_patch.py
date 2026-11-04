"""Byte-preserving edits to top-level Markdown frontmatter fields."""

from __future__ import annotations

from collections.abc import Mapping

from varde_core.yamlio import dump_yaml


def patch_fields(
    raw: bytes,
    *,
    set_fields: Mapping[str, str] | None = None,
    remove_fields: tuple[str, ...] = (),
) -> bytes:
    """Set/remove top-level scalar keys, preserving unrelated source bytes."""
    start, end, newline = _bounds(raw)
    lines = raw[start:end].splitlines(keepends=True)
    edits = dict(set_fields or {})
    for key, value in edits.items():
        if not key or any(c in key for c in ":\r\n"):
            raise ValueError("invalid frontmatter key")
        if any(not character.isprintable() for character in value):
            raise ValueError("frontmatter values must be single-line strings")
    remove = set(remove_fields) | set(edits)
    output: list[bytes] = []
    seen: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        content = line.rstrip(b"\r\n")
        key = (
            content.split(b":", 1)[0].decode("utf-8", "ignore")
            if b":" in content
            else ""
        )
        if key not in remove:
            output.append(line)
            i += 1
            continue
        if key in {"owner", "assigned_to"} and key in seen:
            output.append(line)
            i += 1
            continue
        seen.add(key)
        if key in edits:
            rendered = dump_yaml(edits[key]).splitlines()[1]
            output.append(f"{key}: {rendered}".encode() + newline)
        i += 1
        # Match the historical owner/assign editor: only indented continuations go.
        if key in {"owner", "assigned_to"}:
            while i < len(lines) and lines[i].startswith((b" ", b"\t")):
                i += 1
    missing = [key for key in edits if key not in seen]
    if missing:
        output.extend(
            f"{key}: {dump_yaml(edits[key]).splitlines()[1]}".encode() + newline
            for key in missing
        )
    return raw[:start] + b"".join(output) + raw[end:]


def has_key_line(raw: bytes, key: str) -> bool:
    """Return whether frontmatter contains a top-level line for ``key``."""
    start, end, _ = _bounds(raw)
    prefix = f"{key}:".encode()
    return any(line.startswith(prefix) for line in raw[start:end].splitlines())


def replace_body(raw: bytes, body: bytes) -> bytes:
    """Replace the bytes after frontmatter without reserializing the header."""
    _, end, newline = _bounds(raw)
    body_start = end + 3 + len(newline)
    return raw[:body_start] + body


def _bounds(raw: bytes) -> tuple[int, int, bytes]:
    if raw.startswith(b"---\r\n"):
        newline, start = b"\r\n", 5
    elif raw.startswith(b"---\n"):
        newline, start = b"\n", 4
    else:
        raise ValueError("plan must begin with `---` frontmatter")
    content_start = start
    while start <= len(raw):
        end = raw.find(newline, start)
        if end < 0:
            end = len(raw)
        if raw[start:end] == b"---":
            return content_start, start, newline
        if end == len(raw):
            break
        start = end + len(newline)
    raise ValueError("plan is missing a closing frontmatter delimiter")
