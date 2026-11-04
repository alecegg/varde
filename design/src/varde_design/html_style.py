"""Resolve the style of one HTML element from simple selectors and its style attribute.

Approximation, stated: a selector matches on its last compound (tag, .class, #id);
pseudo-classes, attribute selectors and sibling combinators never match; later
declarations win regardless of specificity.
"""

from __future__ import annotations

import re

from .css_scanner import StyleRule
from .html_scanner import Element

_COMPOUND = re.compile(r"^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$")
_PART = re.compile(r"([.#])([\w-]+)")


def last_compound(selector: str) -> str:
    """Final compound of a selector; empty when it uses a sibling combinator."""
    if "+" in selector or "~" in selector:
        return ""
    words = selector.replace(">", " ").split()
    return words[-1] if words else ""


def selector_matches(selector: str, element: Element) -> bool:
    match = _COMPOUND.match(last_compound(selector))
    if not match:
        return False
    tag, rest = match.groups()
    if tag and tag.lower() != element.tag:
        return False
    for kind, name in _PART.findall(rest):
        if kind == "." and name not in element.classes():
            return False
        if kind == "#" and element.attrs.get("id") != name:
            return False
    return bool(tag or rest)


def element_style(
    element: Element, rules: list[StyleRule], inline: StyleRule | None
) -> dict[str, str]:
    """Property map: matching rules in source order, then the inline style."""
    style: dict[str, str] = {}
    for rule in rules:
        if any(selector_matches(s, element) for s in rule.selector.split(",")):
            style.update({d.prop: d.value for d in rule.declarations})
    if inline:
        style.update({d.prop: d.value for d in inline.declarations})
    return style
