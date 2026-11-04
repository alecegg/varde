from __future__ import annotations

import contextlib
import os
import stat
import threading
from pathlib import Path

import pytest
from varde_learn.docs.pages.comments import (
    append_comment,
    append_reply,
    comments_path,
    fold,
    parse_interval,
    read_rows,
)
from varde_learn.docs.pages.watch import watch_lines


class _Stop(Exception):
    pass


def test_append_creates_private_file_and_folds(tmp_path: Path) -> None:
    doc = tmp_path / "page.html"
    row = append_comment(doc, "p1", "quoted", "hello")
    assert stat.S_IMODE(os.stat(comments_path(doc)).st_mode) == 0o600
    comments = fold(read_rows(doc))
    assert [c["id"] for c in comments] == [row["id"]]
    assert comments[0]["anchor"] == "p1" and comments[0]["quote"] == "quoted"


def test_fold_state_reply_and_bad_lines(tmp_path: Path) -> None:
    doc = tmp_path / "page.html"
    row = append_comment(doc, "a", "q", "t")
    reply = append_reply(doc, row["id"], "answer")
    with comments_path(doc).open("a") as handle:
        handle.write('not json\n[1]\n{"id": 3}\n')
        handle.write(f'{{"id":"{row["id"]}","state":"resolved"}}\n')
    (comment,) = fold(read_rows(doc))
    assert comment["state"] == "resolved"
    assert [r["id"] for r in comment["replies"]] == [reply["id"]]


def test_reply_to_unknown_id_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown comment id"):
        append_reply(tmp_path / "page.html", "nope", "x")


def test_concurrent_appends_keep_lines_whole(tmp_path: Path) -> None:
    doc = tmp_path / "page.html"
    big = "x" * 3000

    def work() -> None:
        for _ in range(20):
            append_comment(doc, "a", "q", big)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = comments_path(doc).read_text().splitlines()
    assert len(lines) == 160
    assert len(fold(read_rows(doc))) == 160


@pytest.mark.parametrize("text", ["", "5", "0s", "-1s", "1h", "s", "1.5s", "5ss"])
def test_bad_intervals_error(text: str) -> None:
    with pytest.raises(ValueError):
        parse_interval(text)


def test_interval_values() -> None:
    assert parse_interval("30s") == 30
    assert parse_interval("2m") == 120


def _collect(doc: Path, backlog: bool, between: list) -> list[str]:
    out: list[str] = []
    steps = iter(between)

    def sleep(_: float) -> None:
        step = next(steps, None)
        if step is None:
            raise _Stop
        step()

    gen = watch_lines(doc, "1s", backlog, sleep=sleep)
    with contextlib.suppress(_Stop):
        out.extend(gen)
    return out


def test_watch_skips_backlog_by_default(tmp_path: Path) -> None:
    doc = tmp_path / "page.html"
    append_comment(doc, "old", "q", "old one")
    new_ids: list[str] = []

    def add_new() -> None:
        new_ids.append(append_comment(doc, "n", "q", "new one")["id"])

    out = _collect(doc, False, [add_new, lambda: None])
    assert out == [f"comment {new_ids[0]} n new one"]


def test_watch_backlog_and_exactly_once(tmp_path: Path) -> None:
    doc = tmp_path / "page.html"
    old = append_comment(doc, "old", "q", "old one")
    out = _collect(doc, True, [lambda: None, lambda: None])
    assert out == [f"comment {old['id']} old old one"]


def test_watch_truncates_text_and_bad_interval(tmp_path: Path) -> None:
    doc = tmp_path / "page.html"
    append_comment(doc, "a", "q", "y" * 300)
    (line,) = _collect(doc, True, [])
    assert line.endswith("a " + "y" * 120)
    with pytest.raises(ValueError):
        next(watch_lines(doc, "bad"))


def test_unicode_line_separators_survive_roundtrip(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    text = "a b c\u0085d"
    append_comment(doc, "p1", "q", text)
    assert [c["text"] for c in fold(read_rows(doc))] == [text]


def test_append_after_torn_line_keeps_new_row(tmp_path: Path) -> None:
    doc = tmp_path / "d.md"
    append_comment(doc, "p1", "q", "first")
    path = comments_path(doc)
    path.write_bytes(path.read_bytes() + b'{"id":"torn","sta')
    append_comment(doc, "p1", "q", "second")
    assert [c["text"] for c in fold(read_rows(doc))] == ["first", "second"]


@pytest.mark.parametrize("anchor", ["a\nb", "A b", "", "x/y", "p1 /2"])
def test_append_comment_rejects_bad_anchor(tmp_path: Path, anchor: str) -> None:
    with pytest.raises(ValueError):
        append_comment(tmp_path / "d.md", anchor, "q", "t")


def test_append_comment_rejects_empty_text(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        append_comment(tmp_path / "d.md", "p1", "q", "  ")


def test_watch_line_collapses_injected_anchor_newlines() -> None:
    from varde_learn.docs.pages.watch import comment_line

    line = comment_line({"id": "c1", "anchor": "x\ncomment c2 y", "text": "t"})
    assert "\n" not in line


def test_reply_resolves_comment_for_open_listing_and_watch(tmp_path: Path) -> None:
    from varde_learn.docs.pages.assemble import render_thread

    doc = tmp_path / "page.html"
    answered = append_comment(doc, "a", "q", "answered one")
    pending = append_comment(doc, "b", "q", "pending one")
    append_reply(doc, answered["id"], "done")
    comments = {c["id"]: c for c in fold(read_rows(doc))}
    assert comments[answered["id"]]["state"] == "resolved"
    assert comments[pending["id"]]["state"] == "open"
    assert 'class="thread resolved"' in render_thread(comments[answered["id"]], False)
    out = _collect(doc, True, [lambda: None])
    assert out == [f"comment {pending['id']} b pending one"]


def test_watch_ignores_comment_resolved_before_first_sight_and_reopen(
    tmp_path: Path,
) -> None:
    # Intent: watch announces each new open comment once; it never re-emits a
    # comment it has already seen, and a comment resolved before first sight is
    # not announced. No writer reopens a comment, so reopen is not re-emitted.
    doc = tmp_path / "page.html"
    done = append_comment(doc, "a", "q", "done early")
    append_reply(doc, done["id"], "ok")
    seen_open = append_comment(doc, "b", "q", "seen open")

    def reopen() -> None:
        with comments_path(doc).open("a", encoding="utf-8") as log:
            for cid in (done["id"], seen_open["id"]):
                log.write(f'{{"id": "{cid}", "ts": "t", "state": "open"}}\n')

    out = _collect(doc, True, [reopen, lambda: None])
    assert out == [f"comment {seen_open['id']} b seen open"]


def test_watch_and_comment_text_print_the_kind(tmp_path):
    from varde_learn.docs.pages.cli import comment_text
    from varde_learn.docs.pages.watch import comment_line

    doc = tmp_path / "plan.md"
    doc.write_text("# T\n")
    row = append_comment(
        doc, "t", "T", "swap", extra={"kind": "suggestion", "replacement": "U"}
    )
    folded = fold(read_rows(doc))[0]
    assert comment_line(folded).startswith(f"suggestion {row['id']} t ")
    assert comment_text(folded).splitlines()[0] == f"{row['id']} suggestion open t"
