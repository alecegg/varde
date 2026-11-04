"""Pass adapter for the scan-time deep call resolver.

The quality contract, section 4, defines call edges as
``{"caller": ..., "site_line": ..., "callee": ..., "kind": ..., "pass": ...}``.
Architecture v2, section 3.4, explicitly lists "constructor edges" among
scan-only resolver additions. The pass therefore includes constructor edges
from the deep resolver; creation sites affect edge coverage and graph measures.

Keep this two-step API stable for the pass: prepare once for the file set, then
look up each file's edges and input digest through the resulting context.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from varde_code import quality_resolve
from varde_code.quality_resolve import coverage
from varde_code.quality_resolve.core import ResolverContext as DeepResolverContext


def _resolver_version() -> str:
    """Hash resolver sources so code changes invalidate cached edges."""
    package = Path(quality_resolve.__file__).parent
    digest = hashlib.blake2b(digest_size=16)
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(path.read_bytes())
    return f"quality-resolve-{digest.hexdigest()}"


RESOLVER_VERSION = _resolver_version()


@dataclass
class PassResolverContext:
    """Pass adapter state, including deterministic per-file failure state."""

    paths: tuple[str, ...]
    facts: Mapping[str, dict]
    deep_context: DeepResolverContext | None
    prepare_error: Exception | None = None
    errors: dict[str, Exception] = field(default_factory=dict)


def _error_digest(error: Exception) -> str:
    return f"resolver-error:{type(error).__name__}"


def opaque_edges(facts: dict) -> list[dict]:
    return [
        {
            "caller": site.get("caller"),
            "site_line": site.get("line"),
            "callee": None,
            "kind": "opaque",
            "pass": "receiver",
        }
        for site in facts.get("call_sites", [])
        if site.get("caller")
    ]


def prepare(
    file_set: Iterable[str], facts_by_file: Mapping[str, dict]
) -> PassResolverContext:
    paths = tuple(sorted(set(file_set)))
    try:
        context = quality_resolve.prepare(paths, facts_by_file)
    except Exception as error:  # noqa: BLE001 - resolver failures degrade per file
        return PassResolverContext(paths, facts_by_file, None, prepare_error=error)
    return PassResolverContext(paths, facts_by_file, context)


def digest_for_file(context: PassResolverContext, path: str) -> str:
    if context.prepare_error is not None:
        context.errors[path] = context.prepare_error
        return _error_digest(context.prepare_error)
    deep_context = context.deep_context
    if deep_context is None:
        raise RuntimeError("resolver context has no deep context or prepare error")
    try:
        return quality_resolve.digest_for_file(deep_context, path)
    except Exception as error:  # noqa: BLE001 - digest failures must not abort a scan
        context.errors[path] = error
        return _error_digest(error)


def edges_for_file(context: PassResolverContext, path: str) -> list[dict]:
    if path in context.errors:
        return opaque_edges(context.facts[path])
    deep_context = context.deep_context
    if deep_context is None:
        raise RuntimeError("resolver context has no deep context or prepare error")
    try:
        return quality_resolve.edges_for_file(deep_context, path)
    except Exception as error:  # noqa: BLE001 - resolver failures degrade per file
        context.errors[path] = error
        return opaque_edges(context.facts[path])


def error_diagnostic(context: PassResolverContext, path: str) -> str | None:
    error = context.errors.get(path)
    if error is None:
        return None
    return f"resolver_error: {type(error).__name__}: {path}"


def has_error(context: PassResolverContext, path: str) -> bool:
    return path in context.errors


def resolver_version() -> str:
    """Return the cache-key version for the pass's deep resolver."""
    return RESOLVER_VERSION


__all__ = [
    "RESOLVER_VERSION",
    "PassResolverContext",
    "coverage",
    "digest_for_file",
    "edges_for_file",
    "error_diagnostic",
    "has_error",
    "opaque_edges",
    "prepare",
    "resolver_version",
]
