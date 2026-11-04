"""Auxiliary graph algorithms and filesystem module resolution helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from varde_code.model import Community, EntityKind


def integer_value(value: object) -> int:
    """Convert a JSON scalar using the built-in integer conversion rules."""
    if not isinstance(value, (int, str, float, bytes, bytearray)):
        raise TypeError(
            "int() argument must be a string, a bytes-like object or a real number"
        )
    return int(value)


@dataclass
class FileNode:
    path: str
    community_id: int | None = None
    fan_in: int = 0
    fan_out: int = 0


@dataclass(frozen=True)
class Edge:
    """Resolved file edge; `to_entity` redirects a call to its declaring file."""

    from_file: int
    to_file: int | None = None
    to_entity: int | None = None
    resolved: bool = True


@dataclass(frozen=True)
class CloneBand:
    id: int
    members: list[int]


def build_nodes(files: Iterable[str]) -> list[FileNode]:
    return [FileNode(path) for path in files]


def compute_fan_metrics(
    nodes: list[FileNode], edges: Iterable[object], entities: Sequence[object]
) -> None:
    fan_in = [0] * len(nodes)
    fan_out = [0] * len(nodes)
    for edge in edges:
        if not _value(edge, "resolved", False):
            continue
        source = _value(edge, "from_file", _value(edge, "from", None))
        if not _valid_id(source, len(nodes)):
            continue
        target_file = _value(edge, "to_file", None)
        target_entity = _value(edge, "to_entity", None)
        if target_file is None and target_entity is None:
            target = _value(edge, "to", None)
            target_file = target if isinstance(target, int) else None
        if target_entity is not None and _valid_id(target_entity, len(entities)):
            target_file = _value(entities[target_entity], "file_id", None)
        fan_out[source] += 1
        if _valid_id(target_file, len(nodes)):
            fan_in[target_file] += 1
    for node, incoming, outgoing in zip(nodes, fan_in, fan_out, strict=False):
        node.fan_in = incoming
        node.fan_out = outgoing


def detect_clone_bands(entities: Sequence[object]) -> list[CloneBand]:
    buckets: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for entity_id, entity in enumerate(entities):
        if _value(entity, "kind") != EntityKind.FUNCTION:
            continue
        signatures = _value(entity, "body_minhash", None)
        if signatures is None:
            continue
        for band, signature in enumerate(signatures[:4]):
            buckets[band][int(signature)].append(entity_id)
    result: list[CloneBand] = []
    for band in range(4):
        for signature in sorted(buckets[band]):
            members = sorted(set(buckets[band][signature]))
            if len(members) >= 2:
                result.append(CloneBand(len(result), members))
    return result


def detect_communities(
    nodes: list[FileNode], edges: Iterable[object], entities: Sequence[object]
) -> list[Community]:
    if not nodes:
        return []
    adjacency: list[dict[int, float]] = [defaultdict(float) for _ in nodes]
    total = 0.0
    for edge in edges:
        if not _value(edge, "resolved", False):
            continue
        source = _value(edge, "from_file", _value(edge, "from", None))
        target = _edge_target_file(edge, entities)
        if (
            not _valid_id(source, len(nodes))
            or not _valid_id(target, len(nodes))
            or source == target
        ):
            continue
        adjacency[source][target] += 1.0
        adjacency[target][source] += 1.0
        total += 1.0
    if total == 0:
        return _singletons(nodes)

    degree = [sum(neighbors.values()) for neighbors in adjacency]
    assignments = list(range(len(nodes)))
    sigma = degree.copy()
    for _ in range(50):
        changed = False
        for node, neighbors in enumerate(adjacency):
            weights: dict[int, float] = defaultdict(float)
            for neighbor, weight in neighbors.items():
                weights[assignments[neighbor]] += weight
            current = assignments[node]
            current_weight = weights.get(current, 0.0)
            removal = -current_weight / total + degree[node] * (
                sigma[current] - degree[node]
            ) / (2 * total * total)
            best, best_gain = current, 0.0
            for candidate, weight in sorted(weights.items()):
                if candidate == current:
                    continue
                gain = (
                    removal
                    + weight / total
                    - degree[node] * sigma[candidate] / (2 * total * total)
                )
                if gain > best_gain + 1e-9 or (
                    abs(gain - best_gain) <= 1e-9 and candidate < best
                ):
                    best, best_gain = candidate, gain
            if best != current:
                sigma[current] -= degree[node]
                sigma[best] += degree[node]
                assignments[node] = best
                changed = True
        if not changed:
            break

    labels: dict[int, str] = {}
    for node, assignment in zip(nodes, assignments, strict=False):
        labels[assignment] = min(labels.get(assignment, node.path), node.path)
    stable_ids = {
        assignment: idx
        for idx, (assignment, _) in enumerate(
            sorted(labels.items(), key=lambda pair: pair[1])
        )
    }
    members: dict[int, list[str]] = defaultdict(list)
    for node, assignment in zip(nodes, assignments, strict=False):
        community_id = stable_ids[assignment]
        node.community_id = community_id
        members[community_id].append(node.path)
    return [Community(id, sorted(paths)) for id, paths in sorted(members.items())]


def resolve_python_module(
    spec: str,
    from_file: str,
    files: list[str],
    *,
    by_path: Mapping[str, int] | None = None,
    package_roots: Mapping[str, set[str]] | None = None,
) -> int | None:
    """Resolve a Python module only within one uniquely identified package."""
    raw = _strip_quotes(spec).strip()
    if not raw:
        return None
    if raw.startswith(("./", "../")):
        base = _normalize(Path(from_file).parent / raw)
    else:
        raw = raw.replace(".", "/")
        first, _, rest = raw.partition("/")
        roots = (package_roots or {}).get(first, set())
        if package_roots is None:
            roots = {
                str(Path(path).parent)
                for path in files
                if Path(path).name == "__init__.py" and Path(path).parent.name == first
            }
        if len(roots) != 1:
            return None
        base = _normalize(Path(next(iter(roots))) / rest) if rest else next(iter(roots))
    candidates = {
        _normalize(Path(f"{base}.py")),
        _normalize(Path(base) / "__init__.py"),
    }
    if by_path is not None:
        matches = {by_path[path] for path in candidates if path in by_path}
    else:
        matches = {
            index
            for index, path in enumerate(files)
            if _normalize(Path(path)) in candidates
        }
    return next(iter(matches)) if len(matches) == 1 else None


def resolve_rust_module(
    spec: str,
    from_file: str,
    files: list[str],
    *,
    by_path: Mapping[str, int] | None = None,
    crate_roots: Mapping[str, Path] | None = None,
    module_bases: Mapping[str, Path] | None = None,
) -> int | None:
    """Resolve an out-of-line Rust module or a crate/self/super module path."""
    raw = _strip_quotes(spec).strip()
    by_path = by_path or {
        _normalize(Path(path)): index for index, path in enumerate(files)
    }
    source = Path(from_file)
    source_key = _normalize(source)
    source_id = by_path.get(source_key)
    if raw.startswith('#[path = "'):
        path, marker, tail = raw[len('#[path = "') :].partition('"]')
        if not marker or not tail.strip().startswith("mod "):
            return None
        return _module_lookup(_normalize(source.parent / path), by_path, source_id)

    is_declaration = raw.startswith("mod ")
    module_base = (module_bases or {}).get(source_key)
    if module_base is None:
        module_base = (
            source.parent
            if source.name in {"lib.rs", "main.rs", "mod.rs"}
            else source.parent / source.stem
        )
    if is_declaration:
        segments = [part.strip() for part in raw[4:].split("::") if part.strip()]
        return _module_file(module_base, segments, by_path, source_id)

    if raw.startswith("::"):
        return None
    path = raw.split(" as ", 1)[0]
    if path.strip() == "self::*":
        return None
    segments = [part.strip() for part in path.split("::") if part.strip()]
    if not segments:
        return None
    root = (crate_roots or {}).get(_normalize(source))
    if root is None and (crate_roots is None or _normalize(source) not in crate_roots):
        root = _rust_crate_root(source, files)
    first, *rest = segments
    if first == "crate":
        if root is None:
            return None
        base, suffix = root, rest
    elif first in {"self", "super"}:
        base = module_base
        suffix = segments
        if suffix[0] == "self":
            suffix = suffix[1:]
        while suffix and suffix[0] == "super":
            base = base.parent
            suffix = suffix[1:]
    else:
        base = module_base
        if _module_file(base, [first], by_path, source_id) is None:
            return None
        suffix = segments
    for length in range(len(suffix), 0, -1):
        found = _module_file(base, suffix[:length], by_path, source_id)
        if found is not None:
            return found
    return _module_owner(base, root, by_path, source_id)


def resolve_module(
    language: str,
    spec: str,
    from_file: str,
    files: list[str],
    *,
    by_path: Mapping[str, int] | None = None,
    package_roots: Mapping[str, set[str]] | None = None,
    crate_roots: Mapping[str, Path] | None = None,
    module_bases: Mapping[str, Path] | None = None,
) -> int | None:
    """Dispatch to language-specific filesystem module rules where defined."""
    if language == "python":
        return resolve_python_module(
            spec, from_file, files, by_path=by_path, package_roots=package_roots
        )
    if language == "rust":
        return resolve_rust_module(
            spec,
            from_file,
            files,
            by_path=by_path,
            crate_roots=crate_roots,
            module_bases=module_bases,
        )
    return None


def _singletons(nodes: list[FileNode]) -> list[Community]:
    result = []
    for index, node in enumerate(nodes):
        node.community_id = index
        result.append(Community(index, [node.path]))
    return result


def _rust_crate_root(source: Path, files: list[str]) -> Path | None:
    normalized = {_normalize(Path(path)) for path in files}
    for parent in source.parents:
        if any(
            _normalize(parent / name) in normalized for name in ("lib.rs", "main.rs")
        ):
            return parent
    return None


def _module_file(
    base: Path, segments: list[str], by_path: Mapping[str, int], excluded: int | None
) -> int | None:
    if not segments:
        return _module_owner(base, None, by_path, excluded)
    directory = base.joinpath(*segments[:-1])
    result = _module_lookup(
        _normalize(directory / f"{segments[-1]}.rs"), by_path, excluded
    )
    if result is not None:
        return result
    return _module_lookup(
        _normalize(directory / segments[-1] / "mod.rs"), by_path, excluded
    )


def _module_owner(
    base: Path,
    crate_root: Path | None,
    by_path: Mapping[str, int],
    excluded: int | None,
) -> int | None:
    candidates = [base / "mod.rs"]
    if crate_root == base:
        candidates = [base / "lib.rs", base / "main.rs"]
    else:
        candidates.append(base.with_suffix(".rs"))
    for candidate in candidates:
        result = _module_lookup(_normalize(candidate), by_path, excluded)
        if result is not None:
            return result
    return None


def _module_lookup(
    path: str, by_path: Mapping[str, int], excluded: int | None
) -> int | None:
    result = by_path.get(path)
    return None if result is None or result == excluded else result


def _edge_target_file(edge: object, entities: Sequence[object]) -> int | None:
    target_entity = _value(edge, "to_entity", None)
    if target_entity is not None:
        if not _valid_id(target_entity, len(entities)):
            return None
        return _value(entities[target_entity], "file_id", None)
    return _value(edge, "to_file", _value(edge, "to", None))


def _value(value: object, key: str, default: object = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _valid_id(value: object, size: int) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _normalize(path: Path) -> str:
    return str(Path(*_collapse(path.parts)))


def _collapse(parts: tuple[str, ...]) -> tuple[str, ...]:
    stack: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if stack and stack[-1] != "..":
                stack.pop()
            else:
                stack.append(part)
        else:
            stack.append(part)
    return tuple(stack)
