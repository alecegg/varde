from pathlib import Path

from varde_data.queue_md import parse_depends_cell, parse_queue_md, render_queue_md

FIXTURES = Path(__file__).parent / "fixtures" / "queue_md"


def test_parse_then_render_is_byte_identical_for_fixtures() -> None:
    source = (FIXTURES / "ux-audit-fixes-1.md").read_text()
    assert render_queue_md(parse_queue_md(source)) == source


def test_edited_value_is_rendered_and_untouched_rows_are_preserved() -> None:
    source = (FIXTURES / "ux-audit-fixes-1.md").read_text()
    doc = parse_queue_md(source)
    rows = list(doc.rows)
    first = rows[0]
    changed_values = dict(first.values)
    changed_values["state"] = "merged"
    rows[0] = type(first)(changed_values, first.extra, first.raw, first.surplus)
    rendered = render_queue_md(
        type(doc)(
            doc.title,
            doc.preamble,
            doc.header,
            tuple(rows),
            doc.trailing,
            doc.separator,
            doc.newline,
            doc.header_raw,
        )
    )
    assert "| A | 2026-10-26-ux-fix-a-settings-safety |" in rendered
    assert "| merged |" in rendered
    assert rows[1].raw in rendered


def test_line_queue_shape_raises_clear_parse_error() -> None:
    source = (FIXTURES / "native-cutover.md").read_text()
    try:
        parse_queue_md(source)
    except ValueError as exc:
        assert "no pipe table" in str(exc)
    else:
        raise AssertionError("line queue was silently accepted as an empty table")


def test_codec_retains_unknown_columns() -> None:
    doc = parse_queue_md("# Queue\n\n| id | mystery |\n|---|---|\n| x | y |\n")
    assert doc.rows[0].extra == {"mystery": "y"}
    assert doc.rows[0].values["mystery"] == "y"


def test_depends_cell_examples() -> None:
    source = (FIXTURES / "ux-audit-fixes-1.md").read_text()
    doc = parse_queue_md(source)
    cells = [row.values["depends_on / serialize-with"] for row in doc.rows]
    parsed = [parse_depends_cell(cell) for cell in cells]
    assert parsed == [
        ([], []),
        ([], ["A"]),
        ([], ["A", "B"]),
        ([], []),
        (["D"], ["C"]),
        (["E"], []),
    ]
    assert parse_depends_cell("none") == ([], [])
    assert parse_depends_cell("free text") == ([], [])
    assert parse_depends_cell("depends_on A and B") == (["A", "B"], [])
    assert parse_depends_cell("depends_on nothing") == ([], [])
    assert all(cell in render_queue_md(doc) for cell in cells)


def test_short_rows_and_empty_cells() -> None:
    doc = parse_queue_md("# Queue\n\n| id | value |\n|---|---|\n| x |\n")
    assert doc.rows[0].values == {"id": "x", "value": ""}


def test_surplus_cells_are_preserved() -> None:
    source = "# Queue\n\n| id | value |\n|---|---|\n| x | y | extra |\n"
    doc = parse_queue_md(source)
    assert doc.rows[0].surplus == ("extra",)
    assert render_queue_md(doc) == source
