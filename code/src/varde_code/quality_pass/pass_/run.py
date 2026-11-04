"""Incremental L1/L1b/L2/L3 orchestration for the scan-time quality pass.

Order of work: read the fast index once (file list and path predicates), reuse
or extract L1 facts, classify paths, resolve L2 edges, then compute per-hop
Merkle fingerprints and reuse or compute L3 measures. Every store write is a
per-file batch, so an interrupted pass leaves a consistent, digest-verified
store and the next pass resumes from it.

L3 measures are module-scoped (the architecture's "edges of the file and of the
files of its module"): the key is the file's forward Merkle fingerprints plus
its L2 key plus a hash of the module's function roles and edges, because
``callers_in_module``, ``fragment_scope``, ``dominated_helpers``, fragment
counts and the expansion cap are not functions of the forward closure alone.
An edit therefore recomputes its module's measures and leaves other modules
bit-identical.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from varde_code.quality_pass import resolve_hook
from varde_code.quality_pass.facts import quality_extractor_version
from varde_code.quality_pass.pathclass import PathPredicates, classify_path
from varde_code.quality_pass.store import Store, open_store, quality_store_path

from . import keys
from .extract import extract_records
from .index_read import (
    IndexedFile,
    IndexView,
    QualityPassError,
    module_package_dirs,
    read_index,
    resolve_fresh_index,
)
from .measures import DEFAULT_T_FRAG, compute_measures, module_signatures

DEFAULT_MAX_WORKERS = 8

__all__ = ["PassSummary", "QualityPassError", "run_quality_pass"]


@dataclass(frozen=True)
class PassSummary:
    """What one pass recomputed, reused and wrote."""

    root: Path
    file_count: int
    facts_recomputed: tuple[str, ...]
    facts_reused: int
    edges_recomputed: tuple[str, ...]
    edges_reused: int
    measures_recomputed: tuple[str, ...]
    measures_reused: int
    path_classes_written: tuple[str, ...]
    exclusions: tuple[tuple[str, str], ...]
    store_path: Path | None
    cached: bool
    workers: int
    no_cache: bool
    garbage_collected: int
    diagnostics: tuple[str, ...] = ()


def run_quality_pass(
    root: str | Path,
    *,
    no_cache: bool = False,
    workers: int | None = None,
) -> PassSummary:
    """Run the quality pass over a repository with a fresh fast index.

    ``no_cache`` recomputes every layer without reading cached rows (rows are
    still written). ``workers`` bounds the parsing process pool; results are
    independent of it.
    """
    root = Path(root)
    resolved_workers = _workers(workers)
    view = read_index(resolve_fresh_index(root), root)
    store = open_store(quality_store_path(root).parent)
    try:
        return _run_pass(
            root,
            view,
            store,
            no_cache=no_cache,
            workers=resolved_workers,
        )
    finally:
        store.close()


def _run_pass(
    root: Path,
    view: IndexView,
    store: Store,
    *,
    no_cache: bool,
    workers: int,
) -> PassSummary:
    facts, facts_keys, facts_recomputed, facts_reused = _collect_facts(
        view, store, no_cache=no_cache, workers=workers
    )
    classes = _classify(view, facts)
    path_classes_written = _write_path_classes(store, classes)
    context = resolve_hook.prepare([item.path for item in view.files], facts)
    edges, edge_keys, edges_recomputed, edges_reused = _collect_edges(
        store, view, facts_keys, context, no_cache=no_cache
    )
    diagnostics = []
    for path in sorted(facts):
        existing = facts[path].setdefault("diagnostics", [])
        retained = [
            item for item in existing if not item.startswith("resolver_error: ")
        ]
        diagnostic = resolve_hook.error_diagnostic(context, path)
        if diagnostic is not None:
            retained.append(diagnostic)
            diagnostics.append(diagnostic)
        if retained != existing:
            facts[path]["diagnostics"] = retained
            store.put_batch(path, {"facts": (facts_keys[path], facts[path])})
    measures_recomputed, measures_reused = _collect_measures(
        store,
        facts,
        edges,
        edge_keys,
        {path: record["module"] for path, record in classes.items()},
        no_cache=no_cache,
    )
    collected = store.collect_garbage(item.path for item in view.files)
    return PassSummary(
        root=root,
        file_count=len(view.files),
        facts_recomputed=tuple(facts_recomputed),
        facts_reused=facts_reused,
        edges_recomputed=tuple(edges_recomputed),
        edges_reused=edges_reused,
        measures_recomputed=tuple(measures_recomputed),
        measures_reused=measures_reused,
        path_classes_written=tuple(path_classes_written),
        exclusions=_exclusions(classes),
        store_path=store.path,
        cached=store.path is not None,
        workers=workers,
        no_cache=no_cache,
        garbage_collected=collected,
        diagnostics=tuple(diagnostics),
    )


def _exclusions(classes: Mapping[str, dict]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (path, str(record["exclusion_reason"]))
            for path, record in classes.items()
            if record.get("excluded")
        )
    )


def _collect_facts(
    view: IndexView, store: Store, *, no_cache: bool, workers: int
) -> tuple[dict[str, dict], dict[str, str], list[str], int]:
    extractor = quality_extractor_version()
    facts: dict[str, dict] = {}
    facts_keys: dict[str, str] = {}
    pending: list[tuple[IndexedFile, bytes]] = []
    for item in view.files:
        raw = item.absolute.read_bytes()
        key = keys.facts_key(keys.content_digest(raw), item.language, extractor)
        facts_keys[item.path] = key
        record = None if no_cache else store.get_facts(item.path, key)
        if record is None:
            pending.append((item, raw))
        else:
            facts[item.path] = record
    reused = len(facts)
    recomputed: list[str] = []
    for path, record in extract_records(pending, workers=workers):
        facts[path] = record
        recomputed.append(path)
        store.put_batch(path, {"facts": (facts_keys[path], record)})
    return facts, facts_keys, recomputed, reused


def _classify(view: IndexView, facts: dict[str, dict]) -> dict[str, dict]:
    classes = {}
    for item in view.files:
        predicates = PathPredicates(
            is_test_path=item.is_test_path,
            is_tooling_path=item.is_tooling_path,
            generated_marker=bool(facts[item.path].get("markers")),
        )
        path_class = classify_path(
            item.path,
            predicates,
            language=item.language,
            package_dirs=module_package_dirs(view, item.language),
        )
        classes[item.path] = _json_row(asdict(path_class))
    return classes


def _write_path_classes(store: Store, classes: dict[str, dict]) -> list[str]:
    written = []
    for path in sorted(classes):
        if store.get_path_class(path) == classes[path]:
            continue
        store.put_batch(path, {"path_classes": ("path-class", classes[path])})
        written.append(path)
    return written


def _collect_edges(
    store: Store,
    view: IndexView,
    facts_keys: dict[str, str],
    context: resolve_hook.PassResolverContext,
    *,
    no_cache: bool,
) -> tuple[dict[str, list[dict]], dict[str, str], list[str], int]:
    edges: dict[str, list[dict]] = {}
    edge_keys: dict[str, str] = {}
    recomputed: list[str] = []
    reused = 0
    for item in view.files:
        digest = resolve_hook.digest_for_file(context, item.path)
        key = keys.edges_key(
            facts_keys[item.path], digest, resolve_hook.resolver_version()
        )
        edge_keys[item.path] = key
        cacheable = not resolve_hook.has_error(context, item.path)
        cached = None if no_cache or not cacheable else store.get_edges(item.path, key)
        if cached is None:
            cached = resolve_hook.edges_for_file(context, item.path)
            recomputed.append(item.path)
            if not resolve_hook.has_error(context, item.path):
                store.put_batch(item.path, {"edges": (key, cached)})
        else:
            reused += 1
        edges[item.path] = cached
    return edges, edge_keys, recomputed, reused


def _collect_measures(
    store: Store,
    facts: dict[str, dict],
    edges: dict[str, list[dict]],
    edge_keys: dict[str, str],
    modules: dict[str, str],
    *,
    no_cache: bool,
) -> tuple[list[str], int]:
    fingerprints = _merkle_fingerprints(facts, edges, edge_keys)
    signatures = module_signatures(facts, edges, modules)
    measure_keys: dict[str, str] = {}
    recomputed: list[str] = []
    reused = 0
    for path in sorted(facts):
        fns = sorted(
            (function["id"], fingerprints[function["id"]])
            for function in facts[path]["functions"]
        )
        key = keys.measure_key(
            module=modules[path],
            edge_key_value=edge_keys[path],
            fingerprints=fns,
            module_signature=signatures[modules[path]],
            tfrag=DEFAULT_T_FRAG,
        )
        measure_keys[path] = key
        cached = None if no_cache else store.get_measures(path, key)
        if cached is None:
            recomputed.append(path)
        else:
            reused += 1
    if recomputed:
        needed = {modules[path] for path in recomputed}
        computed = compute_measures(facts, edges, modules, only_modules=needed)
        for path in recomputed:
            store.put_batch(path, {"measures": (measure_keys[path], computed[path])})
    return recomputed, reused


def _merkle_fingerprints(
    facts: dict[str, dict], edges: dict[str, list[dict]], edge_keys: dict[str, str]
) -> dict[str, str]:
    """Compute m_H per function: m_0 is the file L2 key; a hop hashes callees."""
    base: dict[str, str] = {}
    for path in sorted(facts):
        for function in facts[path]["functions"]:
            base[function["id"]] = edge_keys[path]
    callees: dict[str, list[str]] = defaultdict(list)
    for path in sorted(edges):
        for edge in edges[path]:
            caller = edge.get("caller")
            callee = edge.get("callee")
            if edge.get("kind") == "resolved" and callee in base and caller in base:
                callees[caller].append(callee)
    fingerprints = dict(base)
    for _ in range(keys.H_HOPS):
        fingerprints = {
            function: keys.blake2b_digest(
                keys.canonical_json(
                    [
                        base[function],
                        sorted(fingerprints[c] for c in callees[function]),
                    ]
                )
            )
            for function in sorted(base)
        }
    return fingerprints


def _json_row(value: object) -> dict:
    return json.loads(keys.canonical_json(value))


def _workers(workers: int | None) -> int:
    if workers is not None:
        return max(1, int(workers))
    return max(1, min(DEFAULT_MAX_WORKERS, os.cpu_count() or 1))
