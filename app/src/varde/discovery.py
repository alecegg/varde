"""Discover installed Varde command modules."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from varde_core.module import Module


def discover_modules() -> dict[str, Module]:
    """Load modules registered in the ``varde.modules`` entry-point group."""
    modules: dict[str, Module] = {}
    for point in sorted(
        entry_points(group="varde.modules"), key=lambda item: item.name
    ):
        module = point.load()()
        name = getattr(module, "name", None)
        if not isinstance(name, str) or not name:
            raise TypeError(
                f"entry point {point.name!r} returned a module without a name"
            )
        if name in modules:
            raise ValueError(f"duplicate Varde module name: {name}")
        modules[name] = module
    return modules
