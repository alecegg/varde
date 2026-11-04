"""Compute deterministic component debt vectors from facts or source files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..breakdown import breakdown
from ..calibration import Calibration
from ..scoring import score_scope

_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".go": "go",
    ".java": "java",
    ".cs": "csharp",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
}


def component_vector(
    source_file_or_facts: str | Path | dict[str, Any], calibration: Calibration
) -> dict[str, int]:
    """Return raw component debts for one facts record or source file."""
    if isinstance(source_file_or_facts, dict):
        facts = source_file_or_facts
    else:
        path = Path(source_file_or_facts)
        language = _EXTENSIONS.get(path.suffix.lower())
        if language is None:
            raise ValueError(f"unsupported source file extension: {path.suffix}")
        from varde_code.quality_pass.facts import extract_facts

        facts = extract_facts(path.read_bytes(), language, path.as_posix())
    result = score_scope([facts], calibration)
    return {item["name"]: item["debt"] for item in breakdown(result, calibration)}
