"""The entry point every Varde module provides."""

from typing import Protocol

from .io import Io


class Module(Protocol):
    name: str

    def run(self, argv: list[str], io: Io) -> int: ...

    def help(self, path: str) -> str: ...
