"""Factory for the chat repository."""

from collections.abc import Callable
from pathlib import Path

from varde_data.backends.sqlite.chat import SqliteChat
from varde_data.repos.chat import ChatRepository


def open_chat(
    working_dir: Path,
    backend_name: str = "sqlite",
    *,
    clock: Callable[[], str] | None = None,
) -> ChatRepository:
    if backend_name != "sqlite":
        raise ValueError(f"unknown chat backend: {backend_name}")
    return (
        SqliteChat(working_dir, clock=clock)
        if clock is not None
        else SqliteChat(working_dir)
    )


__all__ = ["open_chat"]
