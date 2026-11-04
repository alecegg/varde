"""YAML front matter recorded at the top of every generated pack."""

from __future__ import annotations

import time
from dataclasses import dataclass
from importlib import metadata

NO_COMMIT = "none"


@dataclass(frozen=True)
class Header:
    kind: str
    commit: str
    scope: str
    generated_at: str
    generator: str
    dirty: bool = False


def generator_name() -> str:
    """Return ``varde <version>``, or ``varde dev`` when not installed."""
    for distribution in ("varde", "varde-code"):
        try:
            return f"varde {metadata.version(distribution)}"
        except metadata.PackageNotFoundError:
            continue
    return "varde dev"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def render_header(header: Header) -> str:
    """Render the front matter block, ending with a blank line."""
    lines = [
        "---",
        f"kind: {header.kind}",
        f"commit: {header.commit}",
        f"generated_at: {header.generated_at}",
        f"scope: {header.scope}",
        f"generator: {header.generator}",
    ]
    if header.dirty:
        lines.append("dirty: true")
    return "\n".join([*lines, "---", "", ""])


def parse_header(text: str) -> Header | None:
    """Parse front matter written by ``render_header``; ``None`` when absent."""
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return None
    values: dict[str, str] = {}
    for line in lines[1 : lines.index("---", 1)]:
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip()
    if not {"kind", "commit", "scope"} <= values.keys():
        return None
    return Header(
        kind=values["kind"],
        commit=values["commit"],
        scope=values["scope"],
        generated_at=values.get("generated_at", ""),
        generator=values.get("generator", ""),
        dirty=values.get("dirty") == "true",
    )
