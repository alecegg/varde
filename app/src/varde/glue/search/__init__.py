"""Shared search command behavior and source adapters."""

from .core import SOURCE_ORDER, parse_search_args, render_json, render_text, search_all

__all__ = [
    "SOURCE_ORDER",
    "parse_search_args",
    "render_json",
    "render_text",
    "search_all",
]
