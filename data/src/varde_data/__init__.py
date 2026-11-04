"""Shared data interfaces and storage implementations for Varde."""

from varde_data.errors import Conflict, DataError, Invalid, Locked, NotFound

__all__ = ["Conflict", "DataError", "Invalid", "Locked", "NotFound"]
