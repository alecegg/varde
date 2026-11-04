"""Compatibility import for the production SQLite message backend."""

from varde_data.backends.sqlite.messages import SQLiteMessages, factory

__all__ = ["SQLiteMessages", "factory"]
