"""Rewrite one block of a markdown doc: direct edit and suggestion accept."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from varde_learn.docs.pages.render import PageBlock, render_page

MAX_SOURCE = 32 * 1024


class EditError(Exception):
    """A refused edit; `status` is the HTTP status the server answers with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class BlockSource:
    block: PageBlock
    source: str  # the block's source lines, line endings removed


def _read_lines(doc: Path) -> list[str]:
    try:
        return doc.read_bytes().decode("utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError) as error:
        raise EditError(500, "document unreadable") from error


def _find_block(lines: list[str], doc_name: str, anchor: str) -> PageBlock:
    text = "".join(lines)
    for block in render_page(text, doc_name).blocks:
        if block.anchor == anchor:
            return block
    raise EditError(404, "unknown block")


def _line_ending(line: str) -> str:
    """The separator `str.splitlines` split this line on (it knows more than \\n)."""
    if line.endswith("\r\n"):
        return "\r\n"
    return line[-1] if len(line.splitlines()[0]) < len(line) else ""


def _source_of(lines: list[str], block: PageBlock) -> str:
    last = lines[block.end - 1]
    kept = [
        *lines[block.start : block.end - 1],
        last[: len(last) - len(_line_ending(last))],
    ]
    return "".join(kept).replace("\r\n", "\n")


def read_block(doc: Path, anchor: str) -> BlockSource:
    lines = _read_lines(doc)
    block = _find_block(lines, doc.name, anchor)
    return BlockSource(block, _source_of(lines, block))


def spliced(lines: list[str], block: PageBlock, new_source: str) -> str:
    """Return the document text with only the block's lines replaced."""
    ending = _line_ending(lines[block.end - 1])
    body = new_source.replace("\r\n", "\n").rstrip("\n")
    if ending == "\r\n":
        body = body.replace("\n", "\r\n")
    return "".join(lines[: block.start]) + body + ending + "".join(lines[block.end :])


def _write_atomic(doc: Path, text: str) -> None:
    doc = doc.resolve()  # replace a symlink's target, keep the link
    mode = doc.stat().st_mode & 0o777
    fd, name = tempfile.mkstemp(dir=doc.parent, prefix=f".{doc.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, doc)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _rewrite(
    doc: Path,
    lock: threading.Lock,
    anchor: str,
    base_hash: str,
    transform: Callable[[str], str],
    after: Callable[[], None] = lambda: None,
) -> None:
    """Under the lock, replace the block's source with `transform(source)`.

    Raises EditError 404 for an unknown block, 409 when `base_hash` is stale.
    """
    with lock:
        lines = _read_lines(doc)
        block = _find_block(lines, doc.name, anchor)
        if block.hash != base_hash:
            raise EditError(409, "stale block hash")
        new_source = transform(_source_of(lines, block))
        if len(new_source.encode("utf-8")) > MAX_SOURCE:
            raise EditError(413, "new source too large")
        try:
            _write_atomic(doc, spliced(lines, block, new_source))
        except OSError as error:
            raise EditError(500, "write failed") from error
        try:
            after()
        except OSError as error:
            raise EditError(500, "document changed but the follow-up failed") from error


def apply_edit(
    doc: Path, lock: threading.Lock, anchor: str, base_hash: str, new_source: str
) -> None:
    _rewrite(doc, lock, anchor, base_hash, lambda _old: new_source)


def accept_replacement(
    doc: Path,
    lock: threading.Lock,
    anchor: str,
    base_hash: str,
    swap: tuple[str, str],
    after: Callable[[], None] = lambda: None,
) -> None:
    """Apply a suggestion: swap = (quote, new); quote must occur exactly once.

    `after` runs under the same lock once the write succeeded.
    """

    quote, new = swap

    def replace_once(source: str) -> str:
        if not quote or source.count(quote) != 1:
            raise EditError(409, "suggestion no longer matches the block")
        return source.replace(quote, new, 1)

    _rewrite(doc, lock, anchor, base_hash, replace_once, after)
