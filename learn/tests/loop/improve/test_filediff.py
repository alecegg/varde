"""Multi-file diff building, parsing and strict application."""

from __future__ import annotations

import pytest
from varde_learn.loop.improve import apply, filediff


def test_empty_file_delete_and_create_keep_header_pairs() -> None:
    gone = filediff.make_file_diff("/a/x.md", "", None)
    assert gone == "--- /a/x.md\n+++ /dev/null\n"
    [parsed] = filediff.parse_diff(gone)
    assert parsed.deletes and not parsed.creates
    assert apply.post_images(gone, {"/a/x.md": ""}) == {"/a/x.md": None}
    made = filediff.make_file_diff("/a/y.md", None, "")
    assert apply.post_images(made, {"/a/y.md": None}) == {"/a/y.md": ""}


def test_delete_removes_file_image() -> None:
    diff = filediff.make_file_diff("/a/x.md", "one\ntwo\n", None)
    assert apply.post_images(diff, {"/a/x.md": "one\ntwo\n"}) == {"/a/x.md": None}


def test_delete_that_leaves_text_or_missing_file_is_refused() -> None:
    diff = filediff.make_file_diff("/a/x.md", "one\ntwo\n", None)
    with pytest.raises(apply.ApplyError):
        apply.post_images(diff, {"/a/x.md": None})
    with pytest.raises(apply.ApplyError, match="leaves text"):
        apply.post_images(diff, {"/a/x.md": "one\ntwo\nthree\n"})


def test_null_on_both_sides_is_rejected() -> None:
    with pytest.raises(filediff.DiffError):
        filediff.parse_diff("--- /dev/null\n+++ /dev/null\n")
