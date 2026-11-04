"""Language coverage for certified cognitive-complexity profiles."""

from __future__ import annotations

from pathlib import Path

from varde_code.parse import language_for_path

CERTIFIED_COMPLEXITY_LANGUAGES = (
    "bash",
    "c",
    "cpp",
    "csharp",
    "dart",
    "elixir",
    "go",
    "haskell",
    "java",
    "javascript",
    "kotlin",
    "lua",
    "php",
    "python",
    "ruby",
    "rust",
    "scala",
    "solidity",
    "swift",
    "tsx",
    "typescript",
)


def has_certified_complexity_profile(path: str | Path) -> bool:
    """Return whether the path's parser language has certified complexity."""
    return language_for_path(path) in CERTIFIED_COMPLEXITY_LANGUAGES
