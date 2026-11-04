"""Actions behind `varde learn docs serve|watch|comments|reply`.

Argv parsing is in cli.py.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from varde_core.envelope import success, tool_error

from varde_learn.docs.pages import blocks, netbind
from varde_learn.docs.pages import serve as serve_module
from varde_learn.docs.pages.assemble import assemble_static
from varde_learn.docs.pages.blocks.quality import quality_warnings
from varde_learn.docs.pages.comments import (
    append_reply,
    fold,
    mark_latest_decisions,
    one_line,
    parse_interval,
    read_rows,
)
from varde_learn.docs.pages.watch import watch_lines


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fail(command: str, code: str, message: str, json_output: bool = False) -> int:
    text = f"varde learn docs {command}: {message}"
    print(_json_text(tool_error(code, text)) if json_output else text, file=sys.stderr)
    return 2


def _missing_doc(command: str, doc: Path, json_output: bool = False) -> int | None:
    if doc.is_file():
        return None
    return _fail(command, "doc_pages_input", f"not a file: {doc}", json_output)


def parse_port(text: str) -> int:
    """Return a TCP port 0-65535; raise ValueError otherwise."""
    if not text.isascii() or not text.isdigit() or int(text) > 65535:
        raise ValueError(f"bad port {text!r}: use an integer 0-65535")
    return int(text)


def serve_doc(
    doc: Path,
    port: int,
    open_browser: bool,
    host: str = netbind.LOOPBACK,
    allow_edit: bool = False,
) -> int:
    if (failure := _missing_doc("serve", doc)) is not None:
        return failure

    def on_ready(url: str) -> None:
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)

    try:
        serve_module.serve(doc, port, on_ready, host, allow_edit)
    except ValueError as error:
        return _fail("serve", "doc_pages_input", str(error))
    except OSError as error:
        return _fail(
            "serve", "doc_pages_serve", netbind.bind_error_message(error, host)
        )
    return 0


def build_doc(doc: Path, out: Path) -> int:
    if (failure := _missing_doc("build", doc)) is not None:
        return failure
    if out.resolve() == doc.resolve():
        return _fail(
            "build", "doc_pages_input", f"--out would overwrite the source: {doc}"
        )
    try:
        out.write_text(assemble_static(doc), encoding="utf-8")
    except OSError as error:
        return _fail("build", "doc_pages_input", f"cannot write {out}: {error}")
    return 0


def watch_doc(
    doc: Path,
    interval: str,
    include_backlog: bool,
    lines: Callable[..., Iterable[str]] = watch_lines,
) -> int:
    if (failure := _missing_doc("watch", doc)) is not None:
        return failure
    try:
        parse_interval(interval)
    except ValueError as error:
        return _fail("watch", "doc_pages_input", str(error))
    try:
        for line in lines(doc, interval, include_backlog):
            print(line, flush=True)
    except KeyboardInterrupt:
        pass
    return 0


def comment_head(comment: dict[str, Any]) -> str:
    if comment.get("kind") == "decision":
        latest = " latest" if comment.get("latest") else ""
        return (
            f"{comment['id']} decision {comment.get('state', '')} "
            f"{comment.get('item', '')} {comment.get('verdict', '')}{latest} "
            f"{comment.get('ts', '')}"
        )
    return (
        f"{comment['id']} {comment.get('kind', 'comment')} "
        f"{comment.get('state', '')} {comment.get('anchor', '')}"
    )


def comment_text(comment: dict[str, Any]) -> str:
    head = one_line(comment_head(comment))
    parts = [head, f"  {one_line(comment.get('text', ''))}"]
    parts.extend(
        f"  reply {one_line(reply.get('actor', ''))}: {one_line(reply.get('text', ''))}"
        for reply in comment.get("replies", [])
    )
    return "\n".join(parts)


def list_comments(
    doc: Path, open_only: bool, json_output: bool, kind: str | None = None
) -> int:
    if (failure := _missing_doc("comments", doc, json_output)) is not None:
        return failure
    rows = mark_latest_decisions(fold(read_rows(doc)))
    rows = [c for c in rows if not open_only or c["state"] == "open"]
    rows = [c for c in rows if kind is None or c.get("kind") == kind]
    if json_output:
        print(_json_text(success({"comments": rows}, {"truncated": False})))
    elif rows:
        print("\n".join(comment_text(row) for row in rows))
    return 0


def reply_comment(doc: Path, comment_id: str, note: str, json_output: bool) -> int:
    if (failure := _missing_doc("reply", doc, json_output)) is not None:
        return failure
    try:
        row = append_reply(doc, comment_id, note)
    except ValueError as error:
        return _fail("reply", "doc_pages_input", str(error), json_output)
    if json_output:
        print(_json_text(success({"reply": row}, {"truncated": False})))
    else:
        print(f"replied {row['id']} to {comment_id}")
    return 0


def block_types() -> tuple[str, ...]:
    return tuple(sorted(blocks.COMPONENT_SPECS))


def show_blocks(name: str | None) -> int:
    print(blocks.type_text(name) if name else blocks.reference_text(), end="")
    return 0


def check_blocks(doc: Path) -> int:
    if (failure := _missing_doc("blocks", doc)) is not None:
        return failure
    errors = blocks.check(doc.read_text(encoding="utf-8"), doc.parent)
    for error in errors:
        print(f"{doc}:{error.line}: {error.rule}: {error.message}")
    tasks = doc.parent / "tasks"
    task_ids = [p.stem for p in tasks.glob("*.md")] if tasks.is_dir() else []
    for warning in quality_warnings(doc.read_text(encoding="utf-8"), task_ids):
        print(f"{doc}:{warning.line}: warning: {warning.rule}: {warning.message}")
    return 1 if errors else 0
