"""Pure text edits of `[default] memory` in the user config. No file access."""

from __future__ import annotations

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.items import Table

from varde_learn.knowledge.memory_config import MemoryConfigError

TABLE = "default"
KEY = "memory"


def set_default_memory(text: str, directory: str) -> str:
    """Return config text with `[default] memory = directory`."""
    if not directory.strip():
        raise MemoryConfigError("memory directory must not be empty")
    document = _parse(text)
    table = document.get(TABLE)
    if table is None:
        document[TABLE] = tomlkit.table()
        table = document[TABLE]
    if not isinstance(table, Table):
        raise MemoryConfigError("`default` is not a table")
    table[KEY] = directory
    return tomlkit.dumps(document)


def unset_default_memory(text: str) -> str:
    """Return config text without `[default] memory`; drop an emptied table."""
    document = _parse(text)
    table = document.get(TABLE)
    if not isinstance(table, Table) or KEY not in table:
        return text
    del table[KEY]
    if not table:
        del document[TABLE]
    return tomlkit.dumps(document)


def _parse(text: str) -> tomlkit.TOMLDocument:
    try:
        return tomlkit.parse(text)
    except ParseError as error:
        raise MemoryConfigError(f"failed to parse memory config: {error}") from error
