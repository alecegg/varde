"""Poll a page's comment log and emit one line per new comment."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from varde_learn.docs.pages.answers import answer_value
from varde_learn.docs.pages.assemble import read_markdown
from varde_learn.docs.pages.comments import (
    ANSWER_KINDS,
    fold,
    fold_with_sources,
    one_line,
    parse_interval,
    read_rows,
)
from varde_learn.docs.pages.include import IncludeError, include_sources


def comment_line(comment: dict) -> str:
    text = one_line(comment.get("text", ""))[:120]
    if comment.get("kind") in ANSWER_KINDS:
        value = one_line(answer_value(comment))
        return (
            f"{comment['kind']} {one_line(comment['id'])} "
            f"{one_line(comment.get('item', ''))} {value} {text}"
        )
    part = f" [{one_line(comment['part'])}]" if comment.get("part") else ""
    return (
        f"{one_line(comment.get('kind', 'comment'))} {one_line(comment['id'])} "
        f"{one_line(comment.get('anchor', ''))}{part} {text}"
    )


def page_comments(doc: Path) -> tuple[list[dict], str | None]:
    """Page comments plus those of included parts, and the include error if any.

    A broken include adds no part comments (their rows stay on disk). The plan
    store is the doc's project store; the daemon passes `<working>/plans`, the
    same directory when the doc lives in that project.
    """
    try:
        sources = include_sources(read_markdown(doc), doc.parent)
    except (IncludeError, OSError) as error:
        return fold(read_rows(doc)), str(error)
    return fold_with_sources(doc, sources), None


def new_open_comments(doc: Path, seen: set[str]) -> list[dict]:
    """Return open comments not in `seen` and add every new id to `seen`."""
    fresh = []
    comments, _ = page_comments(doc)
    for comment in comments:
        if comment["id"] in seen:
            continue
        seen.add(comment["id"])
        if comment.get("state") == "open":
            fresh.append(comment)
    return fresh


def watch_lines(
    doc: Path,
    interval: str,
    include_backlog: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[str]:
    """Yield lines for new comments forever; the caller stops the generator."""
    seconds = parse_interval(interval)
    seen: set[str] = set()
    if not include_backlog:
        seen.update(c["id"] for c in page_comments(doc)[0])
    warned: str | None = None
    while True:
        error = page_comments(doc)[1]
        if error and error != warned:
            print(f"include error: {one_line(error)}", file=sys.stderr, flush=True)
        warned = error
        for comment in new_open_comments(doc, seen):
            yield comment_line(comment)
        sleep(seconds)
