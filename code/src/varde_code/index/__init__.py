"""Code index APIs, imported only when their package attributes are used."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import SCHEMA_VERSION, build_version_fingerprint, initialize, open_database
    from .files import DefaultFileWalker as FileWalker
    from .paths import repo_db_path, repo_identity
    from .persist.graph import SqliteGraphCache as GraphCache
    from .slice import IndexService

_EXPORTS = {
    "SCHEMA_VERSION": (".db", "SCHEMA_VERSION"),
    "build_version_fingerprint": (".db", "build_version_fingerprint"),
    "initialize": (".db", "initialize"),
    "open_database": (".db", "open_database"),
    "repo_db_path": (".paths", "repo_db_path"),
    "repo_identity": (".paths", "repo_identity"),
    "FileWalker": (".files", "DefaultFileWalker"),
    "IndexService": (".slice", "IndexService"),
    "GraphCache": (".persist.graph", "SqliteGraphCache"),
}

__all__ = [
    "SCHEMA_VERSION",
    "FileWalker",
    "GraphCache",
    "IndexService",
    "build_version_fingerprint",
    "initialize",
    "open_database",
    "repo_db_path",
    "repo_identity",
]


def __getattr__(name: str):
    """Load heavier index components only when a caller requests them."""
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
