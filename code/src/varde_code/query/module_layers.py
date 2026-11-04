"""Derive module dependency edges and cycles from file-level dependencies."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from .noise_filter import is_generated_or_vendored_path

MIN_CROSSING_FILES = 3


@dataclass(frozen=True)
class ModuleEdge:
    from_module: str
    to_module: str
    crossing_files: int


@dataclass
class ModuleLayers:
    edges: list[ModuleEdge] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)


def _module(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def compute_module_layers(file_edges: Iterable[tuple[str, str]]) -> ModuleLayers:
    crossings: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for source, target in file_edges:
        if is_generated_or_vendored_path(source) or is_generated_or_vendored_path(
            target
        ):
            continue
        source_module, target_module = _module(source), _module(target)
        if source_module != target_module:
            crossings[source_module, target_module].add((source, target))
    edges = [
        ModuleEdge(source, target, len(files))
        for (source, target), files in sorted(crossings.items())
        if len(files) >= MIN_CROSSING_FILES
    ]
    return ModuleLayers(edges, _detect_cycles(edges))


def _detect_cycles(edges: list[ModuleEdge]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for edge in edges:
        adjacency[edge.from_module].append(edge.to_module)
        nodes.update((edge.from_module, edge.to_module))
    for neighbors in adjacency.values():
        neighbors.sort()

    cycles: list[list[str]] = []
    reported: set[tuple[str, ...]] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str], on_stack: set[str]) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor in on_stack:
                ordered = stack[stack.index(neighbor) :]
                key = tuple(sorted(ordered))
                if key not in reported:
                    reported.add(key)
                    cycles.append(ordered.copy())
            elif neighbor not in visited:
                visit(neighbor, stack, on_stack)
        stack.pop()
        on_stack.remove(node)

    for node in sorted(nodes):
        if node not in visited:
            visit(node, [], set())
    return cycles
