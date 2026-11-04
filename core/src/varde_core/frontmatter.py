"""Parsing and serialization for markdown YAML frontmatter."""

from __future__ import annotations

from typing import Any

from varde_core.yamlio import YamlSyntaxError, dump_yaml, load_yaml


class FrontmatterError(ValueError):
    """The document does not contain valid mapping frontmatter."""


def parse(data: bytes | str) -> tuple[dict[str, Any], str]:
    """Parse a ``---`` delimited YAML mapping and its markdown body."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FrontmatterError(f"concept document must be UTF-8: {exc}") from exc
    else:
        text = data

    if not text.startswith("---\n"):
        raise FrontmatterError(
            "concept document must be delimited by `---` frontmatter markers"
        )
    rest = text[4:]
    end = _closing_delimiter(rest)
    if end is None:
        raise FrontmatterError(
            "concept document must be delimited by `---` frontmatter markers"
        )

    content = rest[:end]
    delimiter_length = 3 if end == 0 else 4
    body = rest[end + delimiter_length :]
    body = body.removeprefix("\n")
    try:
        frontmatter = {} if not content.strip() else load_yaml(content)
    except YamlSyntaxError as exc:
        raise FrontmatterError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise FrontmatterError(
            "frontmatter must be a YAML mapping, got expected a YAML mapping, "
            "e.g. `type: decision`"
        )
    return frontmatter, body


def _closing_delimiter(rest: str) -> int | None:
    offset = 0
    for line in rest.split("\n"):
        if line == "---":
            return max(0, offset - 1)
        offset += len(line) + 1
    return None


def serialize(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a frontmatter mapping and markdown body."""
    if not isinstance(frontmatter, dict):
        raise FrontmatterError("frontmatter must be a YAML mapping")
    yaml = dump_yaml(frontmatter)
    yaml = yaml.removeprefix("---\n")
    return f"---\n{yaml}---\n{body}"


def frontmatter_bounds(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"---\n"):
        raise ValueError("plan must begin with `---` frontmatter")
    start = 4
    while start <= len(data):
        end = data.find(b"\n", start)
        end = len(data) if end < 0 else end
        if data[start:end] == b"---":
            return 4, start
        if end == len(data):
            break
        start = end + 1
    raise ValueError("plan is missing a closing frontmatter delimiter")
