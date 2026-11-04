"""Parse skill requires/recommends relations and expand hard dependencies."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

IMPLICIT_SKILL = "varde-manage"


@dataclass
class Relations:
    """Relations declared by a single skill."""

    requires: list[str] = field(default_factory=list)
    recommends: list[str] = field(default_factory=list)


class RelationError(ValueError):
    """Malformed relations, unknown skills, or requires cycles."""

    def __init__(
        self, kind: str, detail: str | Sequence[str], *, key: str | None = None
    ) -> None:
        self.kind = kind
        self.key = key
        self.detail = detail
        if kind == "malformed":
            message = f"`{key}` is not a flow list of skill names: {detail}"
        elif kind == "unknown":
            message = f"unknown skill `{detail}`"
        else:
            message = f"`requires` cycle: {' -> '.join(detail)}"
        super().__init__(message)

    @classmethod
    def malformed(cls, key: str, value: str) -> RelationError:
        return cls("malformed", value, key=key)

    @classmethod
    def unknown(cls, name: str) -> RelationError:
        return cls("unknown", name)

    @classmethod
    def cycle(cls, path: list[str]) -> RelationError:
        return cls("cycle", path)


def parse(frontmatter: str) -> Relations:
    relations = Relations()
    for line in frontmatter.splitlines():
        key_and_rest = _relation_key(line)
        if key_and_rest is None:
            continue
        key, rest = key_and_rest
        names = _parse_list(key, rest)
        if key == "requires":
            relations.requires = names
        else:
            relations.recommends = names
    return relations


def closure(
    selected: Sequence[str], requires_of: Callable[[str], Sequence[str] | None]
) -> list[str]:
    visited: set[str] = set()
    path: list[str] = []

    def visit(name: str) -> None:
        if name in path:
            start = path.index(name)
            raise RelationError.cycle([*path[start:], name])
        if name in visited:
            return
        required = requires_of(name)
        if required is None:
            raise RelationError.unknown(name)
        path.append(name)
        for dependency in sorted(set(required)):
            visit(dependency)
        path.pop()
        visited.add(name)

    for seed in sorted(set(selected)):
        visit(seed)
    return sorted(visited)


def _relation_key(line: str) -> tuple[str, str] | None:
    for key in ("requires", "recommends"):
        if line.startswith(f"{key}:"):
            return key, line[len(key) + 1 :]
    return None


def _parse_list(key: str, rest: str) -> list[str]:
    value = rest.strip()
    if not value:
        return []

    def malformed() -> RelationError:
        return RelationError.malformed(key, value)

    if value.startswith("["):
        if not value.endswith("]"):
            raise malformed()
        items = value[1:-1].split(",")
        names: list[str] = []
        for item in items:
            if not item.strip():
                continue
            name = _parse_name(item)
            if name is None:
                raise malformed()
            names.append(name)
        return names
    name = _parse_name(value)
    if name is None:
        raise malformed()
    return [name]


def _parse_name(item: str) -> str | None:
    name = item.strip().strip("\"'")
    if not name or any(char.isspace() or char in "[]{}," for char in name):
        return None
    return name
