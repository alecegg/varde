"""Image file facts from the bytes alone: kind from magic bytes, size from the header.

Pure functions, no files. A file is accepted only when its magic bytes name the same
kind as its extension (`png`, `jpeg`, `webp`, `gif`, `svg`).
"""

import re
import struct

EXTENSIONS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".gif": "gif",
    ".svg": "svg",
}
MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
}
MAX_SIDE = 65535
_JPEG_SKIP = {0xC4, 0xC8, 0xCC}
_SVG_ROOT = re.compile(r"<svg\b[^>]*>", re.DOTALL)
_SVG_VIEWBOX = re.compile(r'\bviewBox\s*=\s*["\']([^"\']*)["\']')


def _png(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


def _gif(data: bytes) -> tuple[int, int] | None:
    if data[:6] not in {b"GIF87a", b"GIF89a"} or len(data) < 10:
        return None
    return struct.unpack("<HH", data[6:10])


def _jpeg(data: bytes) -> tuple[int, int] | None:
    if data[:3] != b"\xff\xd8\xff":
        return None
    at = 2
    while at + 9 < len(data):
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if 0xC0 <= marker <= 0xCF and marker not in _JPEG_SKIP:
            height, width = struct.unpack(">HH", data[at + 5 : at + 9])
            return width, height
        if marker == 0xFF:
            at += 1
            continue
        at += 2 + struct.unpack(">H", data[at + 2 : at + 4])[0]
    return None


def _webp(data: bytes) -> tuple[int, int] | None:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or len(data) < 30:
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        wide = int.from_bytes(data[24:27], "little") + 1
        high = int.from_bytes(data[27:30], "little") + 1
        return wide, high
    return None


def _svg_number(root: str, name: str) -> int | None:
    pattern = rf'\b{name}\s*=\s*["\']\s*([0-9.]+)\s*(?:px)?\s*["\']'
    found = re.search(pattern, root)
    return round(float(found.group(1))) if found else None


def _svg(data: bytes) -> tuple[int, int] | None:
    head = data[:65536].decode("utf-8", errors="ignore").lstrip("﻿ \t\r\n")
    found = _SVG_ROOT.search(head)
    if found is None or "\x00" in head:
        return None
    root = found.group(0)
    width, height = _svg_number(root, "width"), _svg_number(root, "height")
    if width and height:
        return width, height
    box = _SVG_VIEWBOX.search(root)
    numbers = box.group(1).replace(",", " ").split() if box else []
    if len(numbers) != 4:
        return None
    try:
        return round(float(numbers[2])), round(float(numbers[3]))
    except ValueError:
        return None


_READERS = {"png": _png, "gif": _gif, "jpeg": _jpeg, "webp": _webp, "svg": _svg}


def read_header(data: bytes, kind: str) -> tuple[int, int] | None:
    """(width, height) in pixels when the bytes really are `kind`, else None."""
    size = _READERS[kind](data)
    if size is None or not all(0 < side <= MAX_SIDE for side in size):
        return None
    return size
