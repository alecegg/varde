"""Typed visual blocks: registry, schemas and validation (renderers come later)."""

from varde_learn.docs.pages.blocks.check import (
    COMPONENT_SPECS,
    CUSTOM_REMOVED,
    SPECS,
    BlockError,
    check,
    check_props,
)
from varde_learn.docs.pages.blocks.reference import reference_text, type_text

TYPES: tuple[str, ...] = tuple(sorted(SPECS))

__all__ = [
    "COMPONENT_SPECS",
    "CUSTOM_REMOVED",
    "SPECS",
    "TYPES",
    "BlockError",
    "check",
    "check_props",
    "reference_text",
    "type_text",
]
