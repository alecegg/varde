from varde_code.index.db import initialize
from varde_code.index.persist import write_entities, write_files, write_symbols
from varde_code.model import (
    Entity,
    EntityKind,
    ExtractOutput,
    FileMeta,
    Span,
    Symbol,
    SymbolKind,
)


def _span():
    return Span(2, 8, 1, 2, 1, 8)


def test_files_entities_and_symbols_are_written_with_global_file_ids(tmp_path):
    connection = initialize(tmp_path / "index.db")
    outputs = [
        ExtractOutput(
            files=["a.py"],
            file_meta=[FileMeta(10, 20, "abc")],
            entities=[
                Entity(
                    EntityKind.FUNCTION,
                    "run",
                    0,
                    _span(),
                    body_minhash=[1, 256],
                    is_async=True,
                ),
                Entity(EntityKind.LITERAL, "42", 0, _span()),
            ],
            symbols=[Symbol(SymbolKind.BINDING, "run", 0, _span())],
        ),
        ExtractOutput(
            files=["b.py"],
            file_meta=[FileMeta(11, 21, "def")],
            entities=[Entity(EntityKind.VARIABLE, "value", 0, _span(), is_test=True)],
            symbols=[Symbol(SymbolKind.REFERENCE, "run", 0, _span())],
        ),
    ]

    file_ids = write_files(connection, outputs)
    entity_ids = write_entities(connection, outputs, file_ids)
    write_symbols(connection, outputs, file_ids)

    assert [
        row[0] for row in connection.execute("SELECT path FROM files ORDER BY id")
    ] == ["a.py", "b.py"]
    assert file_ids.flat == [1, 2]
    assert [
        row[:3]
        for row in connection.execute(
            "SELECT kind, file_id, name FROM entities ORDER BY id"
        )
    ] == [(EntityKind.FUNCTION, 1, "run"), (EntityKind.VARIABLE, 2, "value")]
    assert entity_ids == [1, -1, 2]
    assert connection.execute(
        "SELECT body_minhash, is_async FROM entities WHERE name='run'"
    ).fetchone() == (
        b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00",
        1,
    )
    assert [
        row[:3]
        for row in connection.execute(
            "SELECT kind, file_id, name FROM symbols ORDER BY id"
        )
    ] == [(SymbolKind.BINDING, 1, "run"), (SymbolKind.REFERENCE, 2, "run")]
    assert (
        connection.execute(
            "SELECT is_test FROM entities WHERE name='value'"
        ).fetchone()[0]
        == 1
    )
    connection.close()


def test_empty_write_slices_are_supported(tmp_path):
    connection = initialize(tmp_path / "index.db")
    outputs = [ExtractOutput()]
    file_ids = write_files(connection, outputs)
    assert file_ids.flat == []
    assert write_entities(connection, outputs, file_ids) == []
    write_symbols(connection, outputs, file_ids)
    connection.close()


def test_file_complexity_keeps_test_control_flow(tmp_path):
    connection = initialize(tmp_path / "index.db")
    outputs = [
        ExtractOutput(
            files=["src/lib.rs"],
            file_meta=[FileMeta(10, 20, "abc")],
            entities=[
                Entity(
                    EntityKind.CONTROL_FLOW,
                    "if_statement",
                    0,
                    _span(),
                    is_test=True,
                )
            ],
        )
    ]

    file_ids = write_files(connection, outputs)
    write_entities(connection, outputs, file_ids)

    assert connection.execute("SELECT complexity FROM files").fetchone()[0] == 2
    connection.close()
