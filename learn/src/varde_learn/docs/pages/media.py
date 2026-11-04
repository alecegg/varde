"""Image files for the `image` component: confined reads, magic bytes, size, embedding.

`src` is relative to the document's directory. The file must resolve (symlinks
followed) to a regular file inside that directory, stay under `MAX_BYTES`, and carry
magic bytes that match its extension. This is the only module that reads image files.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from posixpath import splitext

from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.blocks.image import src_fault
from varde_learn.docs.pages.blocks.image_header import EXTENSIONS, MIME, read_header
from varde_learn.docs.pages.lines import Statement, parse_lines

MAX_BYTES = 5 * 1024 * 1024
EMBED_BYTES = 1024 * 1024  # export inlines a file only up to this size


@dataclass(frozen=True)
class Media:
    src: str
    mime: str
    width: int
    height: int
    size: int
    data_url: str = ""  # set only for an export of a file under EMBED_BYTES


@dataclass(frozen=True)
class Problem:
    reason: str


def read_confined(src: str, root: Path) -> tuple[bytes, str] | Problem:
    """(bytes, kind) of the image `src` names under `root`, or why it is refused."""
    if (reason := src_fault(src)) is not None:
        return Problem(reason)
    try:
        base = root.resolve(strict=True)
        path = (base / src).resolve(strict=True)
    except OSError, RuntimeError:
        return Problem(f"image '{src}' not found")
    if not path.is_relative_to(base):
        return Problem(f"image '{src}' resolves outside the page's directory")
    if not path.is_file():
        return Problem(f"image '{src}' is not a regular file")
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        return Problem(f"image '{src}' cannot be read")
    if len(data) > MAX_BYTES:
        return Problem(f"image '{src}' is over the {MAX_BYTES // (1024 * 1024)} MB cap")
    return data, EXTENSIONS[splitext(src.lower())[1]]


def load(src: str, root: Path) -> tuple[bytes, str, tuple[int, int]] | Problem:
    """(bytes, MIME type, (width, height)) of a valid image file, or the refusal."""
    found = read_confined(src, root)
    if isinstance(found, Problem):
        return found
    data, kind = found
    size = read_header(data, kind)
    if size is None:
        return Problem(f"image '{src}' is not a valid {kind} file")
    return data, MIME[kind], size


def probe(src: str, root: Path, *, embed: bool = False) -> Media | Problem:
    """Check one image file; with `embed`, attach a data URL when it is small enough."""
    loaded = load(src, root)
    if isinstance(loaded, Problem):
        return loaded
    data, mime, size = loaded
    inline = embed and len(data) <= EMBED_BYTES
    url = (
        f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}" if inline else ""
    )
    return Media(src, mime, size[0], size[1], len(data), url)


def _image_statements(text: str) -> Iterator[Statement]:
    for fence in find_fences(text, frozenset({"ui"})):
        for statement in parse_lines(fence.body, partial=True).statements:
            if statement.component == "image":
                yield statement


def page_media(
    text: str, doc: Path, *, embed: bool = False
) -> dict[str, Media | Problem]:
    """Probe every distinct, well-formed `src` of the page's image statements."""
    found: dict[str, Media | Problem] = {}
    for statement in _image_statements(text):
        src = statement.props.get("src")
        if isinstance(src, str) and src not in found:
            found[src] = probe(src, doc.parent, embed=embed)
    return found
