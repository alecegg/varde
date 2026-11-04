"""OpenCode version parsing and the supported 2.x baseline."""

from __future__ import annotations

import re

MIN_V2 = (2, 0, 18)
_VERSION = re.compile(
    r"(?<![A-Za-z0-9_.])v?([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?",
    re.IGNORECASE,
)


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text)
    if match is None:
        return None
    try:
        major, minor, patch = (
            int(part) if part is not None else 0 for part in match.groups()
        )
    except ValueError:
        return None
    return major, minor, patch


def is_below_floor(version: tuple[int, int, int]) -> bool:
    return version[0] == 2 and version < MIN_V2
