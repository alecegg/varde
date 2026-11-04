"""Module installation manifests."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass


@dataclass(frozen=True)
class Manifest:
    name: str
    requires: tuple[str, ...]


def parse_manifest(text: str) -> Manifest:
    data = tomllib.loads(text)
    unknown = set(data) - {"name", "requires"}
    if unknown:
        raise ValueError(f"unknown manifest keys: {', '.join(sorted(unknown))}")
    name = data.get("name")
    requires = data.get("requires", [])
    if not isinstance(name, str) or not name:
        raise ValueError("manifest name must be a non-empty string")
    if not isinstance(requires, list) or not all(
        isinstance(item, str) and item for item in requires
    ):
        raise ValueError("manifest requires must be a list of strings")
    return Manifest(name, tuple(requires))


def install_closure(module: str, manifests: dict[str, Manifest]) -> tuple[str, ...]:
    if module not in manifests:
        raise ValueError(f"unknown module: {module}")
    visiting: list[str] = []
    found: set[str] = set()

    def visit(name: str, parent: str | None = None) -> None:
        if name in visiting:
            chain = " -> ".join((*visiting, name))
            raise ValueError(f"module dependency cycle: {chain}")
        if name in found:
            return
        if name not in manifests:
            if parent is None:
                raise ValueError(f"unknown module: {name}")
            raise ValueError(f"module {parent} requires unknown module {name}")
        visiting.append(name)
        for dependency in manifests[name].requires:
            visit(dependency, name)
        visiting.pop()
        found.add(name)

    visit(module)
    return tuple(sorted(found))
