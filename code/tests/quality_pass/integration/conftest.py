"""Session setup for the integration suite: make the grammar cache usable.

Child interpreters inherit ``HOME`` and ``VARDE_TREE_SITTER_CACHE_DIR`` from the
pytest process, so warming every grammar here also serves them. With no
prefetched cache and no network the suite skips with a clear reason instead of
failing deep inside the pass, matching the ``VARDE_TREE_SITTER_CACHE_DIR``
documentation.
"""

from __future__ import annotations

import pytest
from varde_code.parse import parse_source

LANGUAGES = (
    "python",
    "typescript",
    "tsx",
    "java",
    "go",
    "rust",
    "csharp",
    "cpp",
)


@pytest.fixture(autouse=True, scope="session")
def _warm_grammar_cache() -> None:
    for language in LANGUAGES:
        try:
            parse_source(language, "value\n")
        except RuntimeError as error:
            pytest.skip(
                f"tree-sitter grammar cache unavailable for {language}: {error}"
            )
