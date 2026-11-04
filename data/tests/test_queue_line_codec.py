from __future__ import annotations

from pathlib import Path

from varde_data.queue_line import (
    QUEUE_LINE_PATTERN,
    LineQueue,
    LineQueueRow,
    parse_line_queue,
    render_line_queue,
)

FIXTURES = Path(__file__).parent / "fixtures" / "queue_line"


def test_fixture_lines_round_trip_and_strict_flags() -> None:
    for name in ("native-cutover.md", "strict.md"):
        source = (FIXTURES / name).read_text()
        parsed = parse_line_queue(source)
        assert render_line_queue(parsed) == source
        for row in parsed.rows:
            assert row.strict is (
                QUEUE_LINE_PATTERN.fullmatch(row.raw.rstrip("\r\n")) is not None
            )


def test_unknown_fields_and_loose_rows_are_kept() -> None:
    parsed = parse_line_queue("task-x | fix:no | custom:value | free tail\n")
    assert parsed.rows[0].markdown_values == (("fix", "no"), ("custom", "value"))
    assert parsed.rows[0].tail == "free tail"
    assert not parsed.rows[0].strict


def test_changed_row_renders_canonical_form() -> None:
    changed = LineQueue(
        rows=(
            LineQueueRow("task-x", (("fix", "yes"), ("custom", "ok")), "", "", False),
        ),
        header=(),
        passthrough=(),
        layout=(("row", 0),),
    )
    assert render_line_queue(changed) == "task-x | fix:yes | custom:ok\n"


def test_newline_forms_round_trip_byte_identically() -> None:
    for text in (
        "task-x | fix:no | esc:1 | worktree:-",
        "task-x | fix:no | esc:1 | worktree:-\r\n",
        "task-x | fix:no | esc:1 | worktree:-\n",
    ):
        assert render_line_queue(parse_line_queue(text)) == text


def test_two_spaces_separate_free_text_tail() -> None:
    parsed = parse_line_queue("task-x | fix:no | worktree:/workspace/x  note here\n")
    assert parsed.rows[0].markdown_values == (
        ("fix", "no"),
        ("worktree", "/workspace/x"),
    )
    assert parsed.rows[0].tail == "note here"
