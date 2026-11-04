"""Public dispatcher for per-function source measurements."""

from __future__ import annotations

from item_spec_extract_python import _python
from item_spec_extract_tree import _tree, _tree_name
from item_spec_extract_types import ANONYMOUS, TOKEN, Function, SourceSyntaxError

__all__ = [
    "ANONYMOUS",
    "TOKEN",
    "Function",
    "SourceSyntaxError",
    "_tree_name",
    "extract",
]


def extract(language: str, source: str) -> list[Function]:
    if language == "python":
        return _python(source)
    return _tree(language, source)
