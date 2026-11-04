"""Factory for the manager-bot repository."""

from pathlib import Path

from varde_data.backends.sqlite.bot import SqliteBot
from varde_data.repos.bot import BotRepository


def open_bot(working_dir: Path, backend_name: str = "sqlite") -> BotRepository:
    if backend_name != "sqlite":
        raise ValueError(f"unknown bot backend: {backend_name}")
    return SqliteBot(working_dir)


__all__ = ["open_bot"]
