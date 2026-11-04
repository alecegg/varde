import sqlite3

from varde_data.queue import open_queue
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItem, QueueItemInput
from varde_workflow.role_queue_independence import ItemFootprint, independent, ready


def _item(item_id: str, **changes) -> ItemFootprint:
    values = {
        "owned_files": (),
        "depends_on_unmerged": (),
        "serialize_with": (),
        "worktree": f"/worktrees/{item_id}",
    }
    values.update(changes)
    return ItemFootprint(item_id=item_id, **values)


def test_disjoint_items_are_independent():
    candidate = _item("candidate", owned_files=("src/a.py",))
    other = _item("other", owned_files=("src/b.py",))
    assert independent(candidate, [other]).ok


def test_path_prefix_and_glob_overlaps_block():
    candidate = _item("candidate", owned_files=("src/pkg/a.py",))
    prefix = _item("other", owned_files=("src/pkg",))
    glob = _item("other", owned_files=("src/**/*.py",))
    assert independent(candidate, [prefix]).reason
    assert independent(candidate, [glob]).reason


def test_intersecting_globs_are_conservatively_blocked():
    assert (
        independent(
            _item("candidate", owned_files=("a/*.py",)),
            [_item("other", owned_files=("a/b.py",))],
        ).ok
        is False
    )
    assert (
        independent(
            _item("candidate", owned_files=("a/**",)),
            [_item("other", owned_files=("a/x/y.py",))],
        ).ok
        is False
    )
    assert (
        independent(
            _item("candidate", owned_files=("a/*.py",)),
            [_item("other", owned_files=("a/b*.py",))],
        ).ok
        is False
    )


def test_path_aliases_are_normalized_before_overlap_comparison():
    aliases = (
        ("./a", "a"),
        ("a//b", "a/b"),
        ("a/../b", "b"),
        ("a/", "a"),
        (" `a` ", " a "),
    )
    for candidate_path, active_path in aliases:
        candidate = _item("candidate", owned_files=(candidate_path,))
        other = _item("other", owned_files=(active_path,))
        assert independent(candidate, [other]).reason
    assert independent(
        _item("candidate", owned_files=("src/Foo.py",)),
        [_item("other", owned_files=("src/foo.py",))],
    ).reason


def test_unmerged_dependency_and_serialize_with_block():
    candidate = _item(
        "candidate", depends_on_unmerged=("setup",), serialize_with=("serial",)
    )
    assert "depends_on" in independent(candidate, [_item("setup")]).reason
    serial_candidate = _item("candidate", serialize_with=("serial",))
    assert "serialize_with" in independent(serial_candidate, [_item("serial")]).reason


def test_same_worktree_blocks_and_ready_is_boolean():
    candidate = _item("candidate", worktree="/shared")
    other = _item("other", worktree="/shared")
    assert "worktree" in independent(candidate, [other]).reason
    assert ready(QueueItem("candidate", "p"), [QueueItem("other", "p")]) is True
    assert (
        ready(
            QueueItem("candidate", "p", extra={"worktree": "/shared"}),
            [QueueItem("other", "p", extra={"worktree": "/shared"})],
        )
        is False
    )


def test_ready_callback_accepts_sqlite_queue_items(tmp_path):
    initialize(tmp_path)
    repository = open_queue(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    repository.enqueue(
        QueueItemInput(
            "active", "plan", owned_files="a/b.py", state="building", queue_name="q"
        )
    )
    repository.enqueue(
        QueueItemInput("candidate", "plan", owned_files="a/*.py", queue_name="q")
    )

    claimed = repository.claim(
        "q", worker="slot", lease_s=60, now="2026-10-26T12:00:00+00:00", ready=ready
    )

    assert claimed is None
