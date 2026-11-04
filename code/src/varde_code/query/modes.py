"""Mode registration interface shared by query handlers and the dispatcher.

Handlers accept the mode's input object and return its data payload. They may
raise ``QueryError`` for stable query errors. Registration replaces a mode,
which lets concrete query modules register their implementation at import.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .params import QueryError

ModeHandler = Callable[[dict[str, Any]], Any]
_HANDLERS: dict[str, ModeHandler] = {}
_INDEX_SERVICE = None


def set_index_service(service):
    global _INDEX_SERVICE  # noqa: PLW0603 - updates index service override
    _INDEX_SERVICE = service


def index_service():
    return _INDEX_SERVICE


def register_mode(name: str, handler: ModeHandler) -> None:
    if not name or not name.isidentifier():
        raise ValueError(f"invalid query mode name: {name!r}")
    _HANDLERS[name] = handler


def get_mode(name: str) -> ModeHandler:
    try:
        return _HANDLERS[name]
    except KeyError as exc:
        import json

        raise QueryError(
            "unknown_mode", f"unknown query mode {json.dumps(name)}"
        ) from exc


def registered_modes() -> tuple[str, ...]:
    return tuple(_HANDLERS)
