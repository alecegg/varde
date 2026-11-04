"""Hard precondition: a cell audits rendered components, not a code block.

A page that shows `ui` fences as plain code has no widgets to fail, so every
audit would pass vacuously. `NotRendered` is not an AssertionError, so a
pending-family `xfail(raises=AssertionError)` cannot hide it.
"""

from __future__ import annotations

import re
from typing import Any

STATEMENT = re.compile(r"^[A-Za-z][\w-]*\s*=\s*([a-z][\w-]*)\(", re.MULTILINE)
ROOTS_JS = r"""() => ({
  roots: [...document.querySelectorAll('.vb')].map((n) => [...n.classList]),
  code: [...document.querySelectorAll('pre')].map((n) => (n.textContent || '').slice(0, 4000)),
})"""


class NotRendered(Exception):
    """The page shows component source instead of rendered components."""


def components_in(text: str) -> list[str]:
    """Component names of every `ui` statement in a fixture, includes excluded."""
    names = STATEMENT.findall(text)
    return [n for n in names if n != "include"]


def not_rendered(text: str, page: dict[str, Any]) -> list[str]:
    """Reasons the page lacks the fixture's components (empty when rendered)."""
    names = components_in(text)
    roots: list[list[str]] = page["roots"]
    problems = [
        f"no .vb.{n} element for the '{n}' statement"
        for n in sorted(set(names))
        if not any(n in classes for classes in roots)
    ]
    if len(roots) < len(names):
        problems.append(f"{len(roots)} .vb roots for {len(names)} component statements")
    problems += [
        "a <pre> block shows a component statement as code"
        for code in page["code"]
        if STATEMENT.search(code)
    ][:1]
    return problems


# ruff: noqa: E501
