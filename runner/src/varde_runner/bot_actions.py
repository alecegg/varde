"""Small pure helpers shared by the manager bot action handlers."""

from __future__ import annotations

import re

PROVENANCE_LINE = "[from manager bot]"
_FRONTMATTER = re.compile(
    rb"\A---[^\r\n]*\r?\n.*?^---[ \t]*(?:\r?\n|$)", re.DOTALL | re.MULTILINE
)


def with_provenance(text: str) -> str:
    """Add one provenance line without duplicating an existing prefix."""
    if text.splitlines()[:1] == [PROVENANCE_LINE]:
        return text
    return f"{PROVENANCE_LINE}\n{text}"


def replace_plan_body(original: bytes, body: str) -> bytes | None:
    """Replace a plan's body while preserving its frontmatter bytes exactly."""
    match = _FRONTMATTER.match(original)
    if match is None:
        return None
    return match.group(0) + body.encode("utf-8")
