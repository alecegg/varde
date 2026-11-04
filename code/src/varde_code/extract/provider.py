"""Extraction provider that combines entities and function complexity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from varde_code.complexity import FunctionComplexity, function_complexities
from varde_code.extract.entity import extract_file as extract_entities
from varde_code.model import Diagnostic, ExtractOutput


@dataclass
class ExtractionOutput(ExtractOutput):
    """Standard extraction data plus per-function complexity metrics."""

    _complexities: list[FunctionComplexity] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    @property
    def complexities(self) -> list[FunctionComplexity]:
        if self._complexities is None:
            self._complexities = function_complexities(self.entities)
        return self._complexities


class CodeExtractionProvider:
    """Implement the core ``ExtractionProvider`` seam."""

    def extract(self, path: Path, source: str, language: str) -> ExtractionOutput:
        output = extract_entities(str(path), source, language)
        diagnostics = list(output.diagnostics)
        if output.has_parse_error:
            diagnostics.append(
                Diagnostic(
                    0, str(path), "syntax error — partial extract kept", "warning"
                )
            )
        return ExtractionOutput(
            entities=output.entities,
            symbols=output.symbols,
            diagnostics=diagnostics,
            files=output.files,
            file_meta=output.file_meta,
        )


def extract_file(path: Path, source: str, language: str) -> ExtractionOutput:
    """Extract one file's entities, symbols, and per-function complexity."""
    return CodeExtractionProvider().extract(path, source, language)
