"""Shared test helpers for knowledge tests."""

from __future__ import annotations

import tempfile
from pathlib import Path


def tempdir(tag: str) -> Path:
    """Create a fresh, uniquely named temporary directory."""
    return Path(tempfile.mkdtemp(prefix=f"knowledge-{tag}-"))
