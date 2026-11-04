"""SQLite connection setup shared by Varde stores."""

from typing import Any


def configure_connection(connection: Any) -> None:
    configure_connection_options(connection)
    configure_journal_mode(connection)


def configure_connection_options(connection: Any) -> None:
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")


def configure_journal_mode(connection: Any) -> None:
    connection.execute("PRAGMA journal_mode = WAL")
