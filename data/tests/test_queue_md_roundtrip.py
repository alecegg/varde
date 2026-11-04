import sqlite3
from pathlib import Path

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.errors import Invalid
from varde_data.queue_md import parse_queue_md
from varde_data.queue_sync import (
    export_queue_md,
    import_queue_md,
    record_queue_md_export,
)

FIXTURE = Path(__file__).parent / "fixtures" / "queue_md" / "ux-audit-fixes-1.md"


def test_import_export_preserves_every_markdown_column(
    tmp_path: Path, monkeypatch
) -> None:
    working = tmp_path / "working"
    queue_path = working / "plans" / "bundle" / "queue.md"
    queue_path.parent.mkdir(parents=True)
    source = FIXTURE.read_text()
    queue_path.write_text(source)
    monkeypatch.chdir(tmp_path)

    report = import_queue_md(queue_path, "bundle")
    rendered = export_queue_md(working, "bundle")

    assert (report.added, report.updated, report.unchanged, report.skipped) == (
        6,
        0,
        0,
        (),
    )
    assert [row.values for row in parse_queue_md(rendered).rows] == [
        row.values for row in parse_queue_md(source).rows
    ]
    assert not (tmp_path / ".cache").exists()
    queue_path.write_text(rendered)
    record_queue_md_export(working, "bundle", rendered)
    assert import_queue_md(queue_path, "bundle").unchanged == 6


def test_hand_edit_updates_store_before_export(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    queue_path = working / "plans" / "bundle" / "queue.md"
    queue_path.parent.mkdir(parents=True)
    source = FIXTURE.read_text()
    queue_path.write_text(source)
    monkeypatch.chdir(working)
    import_queue_md(queue_path, "bundle")
    rendered = export_queue_md(working, "bundle")
    record_queue_md_export(working, "bundle", rendered)
    store = SQLiteQueue(working / ".cache/data/queue.sqlite3")
    store.transition("bundle", "A", "building", actor="worker")
    report = import_queue_md(queue_path, "bundle")
    assert store.get("bundle", "A").state == "building"
    assert report.conflicts == ("A",)

    # Rendering without an acknowledgement must leave the export hash intact.
    before = import_queue_md(queue_path, "bundle")
    assert before.conflicts == ("A",)
    export_queue_md(working, "bundle")
    assert import_queue_md(queue_path, "bundle").conflicts == ("A",)

    # The original hand edit is applied only to its edited cell.
    store.transition("bundle", "A", "queued", actor="worker")

    edited = source.replace("| A |", "| A |", 1).replace(
        "UX-001, UX-002, UX-003", "edited finding", 1
    )
    queue_path.write_text(edited)
    edited_report = import_queue_md(queue_path, "bundle")
    assert edited_report.updated == 1
    rendered_after_edit = export_queue_md(working, "bundle")
    assert "edited finding" in rendered_after_edit
    with sqlite3.connect(working / ".cache/data/queue.sqlite3") as db:
        assert (
            db.execute(
                "SELECT last_export_hash FROM queue_meta WHERE queue_name='bundle'"
            ).fetchone()[0]
            is None
        )
    assert import_queue_md(queue_path, "bundle").unchanged == 6


def test_non_table_queue_is_reported_as_skipped(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "queue_md" / "native-cutover.md"
    path = tmp_path / "plans" / "native" / "queue.md"
    path.parent.mkdir(parents=True)
    path.write_text(source.read_text())

    report = import_queue_md(path, "native")

    assert report.added == 0
    assert report.skipped and "no pipe table" in report.skipped[0]


def test_empty_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "plans" / "bad" / "queue.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Queue\n\n| id | state |\n|---|---|\n| | queued |\n")
    try:
        import_queue_md(path, "bad")
    except Invalid as exc:
        assert "row 1" in str(exc)
    else:
        raise AssertionError("empty id must fail")

    path.write_text(
        "# Queue\n\n| id | state |\n|---|---|\n| x | queued |\n| x | queued |\n"
    )
    try:
        import_queue_md(path, "bad")
    except Invalid as exc:
        assert "duplicate id" in str(exc)
    else:
        raise AssertionError("duplicate id must fail")


def test_export_refreshes_hand_edit_baseline(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    queue_path = working / "plans" / "bundle" / "queue.md"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(FIXTURE.read_text())
    monkeypatch.chdir(working)
    import_queue_md(queue_path, "bundle")
    store = SQLiteQueue(working / ".cache/data/queue.sqlite3")
    store.transition("bundle", "A", "building", actor="worker")
    rendered = export_queue_md(working, "bundle")
    queue_path.write_text(rendered)
    record_queue_md_export(working, "bundle", rendered)
    store.transition("bundle", "A", "in_review", actor="worker")
    edited = rendered.replace("UX-001, UX-002, UX-003", "edited finding", 1)
    assert edited != rendered
    queue_path.write_text(edited)

    import_queue_md(queue_path, "bundle")

    assert store.get("bundle", "A").state == "in_review"
    assert store.get("bundle", "A").findings == "edited finding"
