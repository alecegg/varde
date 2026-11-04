"""Route parser calls to the backend selected by each language module."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import TYPE_CHECKING

from varde_code.parse import ParsedFile, Parser, TreeSitterParser, language_name

if TYPE_CHECKING:
    from types import ModuleType


class ParserAdapter:
    """Implement the shared parser protocol using language ``BACKEND`` values."""

    def __init__(self, backends: Mapping[str, Parser] | None = None) -> None:
        self._backends = {"tree-sitter": TreeSitterParser(), **(backends or {})}

    def parse(self, language: str, source: str) -> ParsedFile:
        name = language_name(language)
        backend = self._backend_module(name)
        return backend.parse(name, source)

    def _backend_module(self, language: str) -> Parser:
        try:
            module: ModuleType = import_module(f"varde_code.extract.langs.{language}")
        except ModuleNotFoundError as error:
            if error.name not in {
                "varde_code.extract.langs",
                f"varde_code.extract.langs.{language}",
            }:
                raise
            return self._backends["tree-sitter"]
        selected = getattr(module, "BACKEND", "tree-sitter")
        if isinstance(selected, str):
            try:
                return self._backends[selected]
            except KeyError as error:
                raise ValueError(
                    f"no parser registered for backend: {selected}"
                ) from error
        return selected
