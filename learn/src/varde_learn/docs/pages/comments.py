"""Append-only comment log for an interactive doc page: store, fold, reply."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from varde_learn.docs.pages.include import IncludeSource

_KEPT_KEYS = (
    "id", "ts", "anchor", "quote", "text", "state", "actor",
    "replacement", "item", "verdict", "value",
)  # fmt: skip
KINDS = ("comment", "suggestion", "drift", "decision", "answer")
ANSWER_KINDS = ("decision", "answer")  # a `decision` row is read as an answer
_ANCHOR = re.compile(r"[a-z0-9-]+(/[0-9]+)?")
_INTERVAL = re.compile(r"(\d+)([sm])")
# C0 and C1 controls (tab, newline, return allowed), NUL, bidi overrides and isolates.
CONTROLS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def one_line(value: object) -> str:
    """Text for one terminal line: controls replaced, whitespace collapsed."""
    return " ".join(CONTROLS.sub(" ", str(value)).split())


def comments_path(doc: Path) -> Path:
    return doc.with_name(doc.name + ".comments.jsonl")


def parse_interval(text: str) -> float:
    """Return seconds for `<N>s` or `<N>m`; raise ValueError otherwise."""
    match = _INTERVAL.fullmatch(text.strip())
    if match is None or int(match.group(1)) == 0:
        raise ValueError(f"bad interval {text!r}: use <N>s or <N>m, N > 0")
    return int(match.group(1)) * (60 if match.group(2) == "m" else 1)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _append_row(path: Path, row: dict[str, Any]) -> None:
    """One `O_APPEND` write of one line; refuses a symlinked log.

    A log whose last byte is not a newline (a torn earlier write) gets a leading
    newline inside the same write, decided from the descriptor itself.
    """
    encoded = (
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_APPEND | os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise ValueError(f"cannot write {path.name}: not a regular file") from error
    try:
        size = os.fstat(descriptor).st_size
        if size and os.pread(descriptor, 1, size - 1) != b"\n":
            encoded = b"\n" + encoded
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("incomplete comment append")
    finally:
        os.close(descriptor)


def append_comment(
    doc: Path,
    anchor: str,
    quote: str,
    text: str,
    actor: str = "user",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a comment row; `extra` carries kind, replacement, item, verdict."""
    if _ANCHOR.fullmatch(anchor) is None:
        raise ValueError(f"bad anchor {anchor!r}")
    if not text.strip():
        raise ValueError("empty comment text")
    row = {
        "id": "c" + secrets.token_hex(8),
        "ts": _now(),
        "anchor": anchor,
        "quote": quote,
        "text": text,
        "state": "open",
        "actor": actor,
        **(extra or {}),
    }
    _append_row(comments_path(doc), row)
    return row


def mark_applied(doc: Path, comment_id: str, actor: str) -> None:
    """Resolve a suggestion and record who applied it."""
    row = {
        "id": comment_id,
        "ts": _now(),
        "state": "resolved",
        "applied_by": actor,
    }
    _append_row(comments_path(doc), row)


def append_reply(
    doc: Path, comment_id: str, text: str, actor: str = "agent"
) -> dict[str, Any]:
    if not any(c["id"] == comment_id for c in fold(read_rows(doc))):
        raise ValueError(f"unknown comment id {comment_id!r}")
    row = {
        "id": "r" + secrets.token_hex(4),
        "reply_to": comment_id,
        "ts": _now(),
        "text": text,
        "actor": actor,
    }
    _append_row(comments_path(doc), row)
    resolved = {"id": comment_id, "ts": row["ts"], "state": "resolved"}
    _append_row(comments_path(doc), resolved)
    return row


def mark_latest_decisions(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy answer rows, flagging `latest` on the newest answer per block id."""
    newest: dict[str, str] = {}
    for row in comments:
        if row.get("kind") in ANSWER_KINDS and isinstance(row.get("item"), str):
            newest[row["item"]] = row["id"]
    return [
        {**row, "latest": newest.get(row.get("item", "")) == row["id"]}
        if row.get("kind") in ANSWER_KINDS
        else row
        for row in comments
    ]


def read_rows(doc: Path) -> list[dict[str, Any]]:
    """Parse the log, skipping bad lines; a missing log is empty."""
    try:
        text = comments_path(doc).read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return []
    rows = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError, TypeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            rows.append(row)
    return rows


def fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold rows into comments; later state rows and replies attach by id."""
    comments: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = row["id"]
        parent = row.get("reply_to")
        if isinstance(parent, str):
            if parent in comments and isinstance(row.get("text"), str):
                comments[parent]["replies"].append(
                    {k: row[k] for k in ("id", "ts", "text", "actor") if k in row}
                )
        elif row.get("state") in {"open", "resolved"} and cid in comments:
            comments[cid]["state"] = row["state"]
            if isinstance(row.get("applied_by"), str):
                comments[cid]["applied_by"] = row["applied_by"]
        elif row.get("state") == "open" and isinstance(row.get("text"), str):
            comments[cid] = {k: row[k] for k in _KEPT_KEYS if k in row}
            kind = row.get("kind")
            comments[cid]["kind"] = kind if kind in KINDS else "comment"
            comments[cid]["replies"] = []
    return list(comments.values())


# --- comments on included parts ------------------------------------------------


def read_source_markdown(path: Path, limit: int) -> str:
    """Read at most `limit` bytes of a regular file without following a symlink."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError(f"include source '{path.name}' is unreadable") from error
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"include source '{path.name}' is not a regular file")
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"include source '{path.name}' is too large")
    return data.decode("utf-8", errors="replace")


def source_anchors(source: IncludeSource) -> tuple[frozenset[str], frozenset[str]]:
    """Anchors inside the include's selected region, and every anchor of the source.

    The source is re-read and re-parsed, so a comment can only land on a block
    that exists now; raises ValueError when the source cannot be read.
    """
    # Lazy: `select` imports the page renderer, which imports this module.
    from varde_learn.docs.pages.include import MAX_SOURCE_BYTES
    from varde_learn.docs.pages.select import read_source

    blocks = read_source(read_source_markdown(source.path, MAX_SOURCE_BYTES)).blocks
    inside = frozenset(
        b.anchor for b in blocks if b.start >= source.start and b.end <= source.end
    )
    return inside, frozenset(b.anchor for b in blocks)


def source_comments(source: IncludeSource, part: str) -> list[dict[str, Any]]:
    """Folded comments of a source's sidecar that belong to the include `part`.

    Rows anchored inside the selected region are kept; rows whose anchor no
    longer exists anywhere in the source are kept and flagged `orphaned`; rows
    on other parts of the source are left to the pages that include them.
    """
    if comments_path(source.path).is_symlink():
        return []
    try:
        inside, every = source_anchors(source)
    except ValueError:
        return []
    kept = []
    for comment in fold(read_rows(source.path)):
        if comment.get("kind") != "comment":
            continue  # answers, drift and suggestions belong to the source page
        anchor = comment.get("anchor", "")
        if anchor in inside:
            kept.append({**comment, "part": part})
        elif anchor not in every:
            kept.append({**comment, "part": part, "orphaned": True})
    return kept


def fold_with_sources(
    doc: Path, sources: Mapping[str, IncludeSource]
) -> list[dict[str, Any]]:
    """The page's own comments plus those of every included source part."""
    merged = fold(read_rows(doc))
    for part, source in sources.items():
        merged += source_comments(source, part)
    return merged


def append_part_comment(
    source: IncludeSource,
    anchor: str,
    quote: str,
    text: str,
    actor: str = "user",
) -> dict[str, Any]:
    """Append a comment to a source's sidecar; ValueError unless it is safe.

    The anchor must be inside the include's selected region of the source as it
    is now. The sidecar must sit beside the source (no redirected directory) and
    must not be a symlink; `_append_row` opens it with `O_NOFOLLOW`.
    """
    path = comments_path(source.path)
    try:
        moved = source.path.resolve(strict=True) != source.path
        redirected = path.parent.resolve(strict=True) != source.path.parent
    except OSError as error:
        raise ValueError("include source moved or changed") from error
    if moved or redirected or path.is_symlink():
        raise ValueError("comment log of the include source is not writable")
    if anchor not in source_anchors(source)[0]:
        raise ValueError(f"anchor {anchor!r} is outside the included part")
    return append_comment(source.path, anchor, quote, text, actor)
