"""Write extracted files, entities, and symbols to the code index."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from varde_code.complexity import counts_toward_file_complexity
from varde_code.model import EntityKind, ExtractOutput

_BATCH_ROWS = 50  # 18 entity columns stay below SQLite's 999-variable limit.
_DROPPED_KINDS = {
    EntityKind.LITERAL,
    EntityKind.MEMBER_ACCESS,
    EntityKind.CATCH,
    EntityKind.THROW,
}


@dataclass(frozen=True)
class FileIds:
    """Database file IDs, grouped by extraction and flattened in input order."""

    flat: list[int]
    offsets: list[int]

    def get(self, output_index: int, local_file_id: int) -> int:
        return self.flat[self.offsets[output_index] + local_file_id]


def write_files(
    connection: sqlite3.Connection, outputs: Sequence[ExtractOutput]
) -> FileIds:
    """Insert file rows in output order and return their database IDs."""
    flat: list[int] = []
    offsets: list[int] = []
    for output in outputs:
        offsets.append(len(flat))
        metadata = output.file_meta
        rows = [
            (
                path,
                metadata[index].mtime if index < len(metadata) else 0,
                metadata[index].size if index < len(metadata) else 0,
                metadata[index].content_hash if index < len(metadata) else "",
                1,
                0,
            )
            for index, path in enumerate(output.files)
        ]
        for chunk in _chunks(rows, 200):
            placeholders = ", ".join(["(?, ?, ?, ?, ?, ?)"] * len(chunk))
            cursor = connection.execute(
                "INSERT INTO files(path, mtime, size, content_hash, complexity, churn) VALUES "
                + placeholders,
                [value for row in chunk for value in row],
            )
            last_id = cursor.lastrowid
            if last_id is None:
                raise RuntimeError("SQLite did not report inserted file row IDs")
            flat.extend(range(last_id - len(chunk) + 1, last_id + 1))
    return FileIds(flat, offsets)


def write_entities(
    connection: sqlite3.Connection, outputs: Sequence[ExtractOutput], file_ids: FileIds
) -> list[int]:
    """Insert persisted entities and return IDs by original flattened entity index.

    Dropped entity kinds receive ``-1`` to preserve the extractor's flat indices.
    """
    ids: list[int] = []
    rows = []
    for output_index, output in enumerate(outputs):
        for entity in output.entities:
            if entity.kind in _DROPPED_KINDS:
                ids.append(-1)
                continue
            if entity.body_minhash is None:
                minhash = None
            else:
                minhash = b"".join(
                    int(value).to_bytes(8, "little", signed=False)
                    for value in entity.body_minhash
                )
            rows.append(
                (
                    entity.kind.as_i64(),
                    file_ids.get(output_index, entity.file_id),
                    entity.name,
                    entity.span.start_byte,
                    entity.span.end_byte,
                    entity.span.start_line,
                    entity.span.start_col,
                    entity.span.end_line,
                    entity.span.end_col,
                    entity.enclosing_function,
                    entity.method,
                    entity.path,
                    entity.status,
                    entity.body_shape,
                    minhash,
                    entity.is_async,
                    int(entity.is_test),
                    entity.owner_type,
                )
            )
            ids.append(0)

    kept_index = 0
    for chunk in _chunks(rows, _BATCH_ROWS):
        placeholders = ", ".join(["(" + ", ".join(["?"] * 18) + ")"] * len(chunk))
        cursor = connection.execute(
            "INSERT INTO entities(kind, file_id, name, start_byte, end_byte, start_line, start_col, "
            "end_line, end_col, enclosing_function, method, path, status, body_shape, body_minhash, "
            f"is_async, is_test, owner_type) VALUES {placeholders}",
            [value for row in chunk for value in row],
        )
        first_id = (cursor.lastrowid or 0) - len(chunk) + 1
        for offset in range(len(chunk)):
            while ids[kept_index] == -1:
                kept_index += 1
            ids[kept_index] = first_id + offset
            kept_index += 1
    for output_index, output in enumerate(outputs):
        counts = [0] * len(output.files)
        for entity in output.entities:
            if counts_toward_file_complexity(entity):
                counts[entity.file_id] += 1
        connection.executemany(
            "UPDATE files SET complexity=? WHERE id=?",
            (
                (1 + count, file_ids.get(output_index, index))
                for index, count in enumerate(counts)
            ),
        )
    return ids


def write_symbols(
    connection: sqlite3.Connection, outputs: Sequence[ExtractOutput], file_ids: FileIds
) -> None:
    """Insert symbols in flattened extraction order."""
    rows = [
        (
            symbol.kind.as_i64(),
            file_ids.get(output_index, symbol.file_id),
            symbol.name,
            symbol.span.start_byte,
            symbol.span.end_byte,
            symbol.span.start_line,
            symbol.span.start_col,
            symbol.span.end_line,
            symbol.span.end_col,
        )
        for output_index, output in enumerate(outputs)
        for symbol in output.symbols
    ]
    for chunk in _chunks(rows, 100):
        placeholders = ", ".join(["(" + ", ".join(["?"] * 9) + ")"] * len(chunk))
        connection.execute(
            "INSERT INTO symbols(kind, file_id, name, start_byte, end_byte, start_line, start_col, "
            f"end_line, end_col) VALUES {placeholders}",
            [value for row in chunk for value in row],
        )


def _chunks(rows: list[tuple], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
