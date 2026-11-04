"""Equivalence and scale test for the prepared depth graph."""

from __future__ import annotations

import random
import time
from collections import defaultdict

from varde_code.quality_pass.graph import chain_depth, cross_module_depth, depth_graph

# --- Reference: the previous per-call graph implementation, kept verbatim. ---


_OPAQUE_KINDS = {"ambiguous", "opaque"}


def old_function_metadata(facts, trivial_ids=()):
    metadata = {}
    for item in facts or ():
        function_id = item.get("id")
        if function_id:
            metadata[function_id] = {
                **item,
                "_trivial": bool(
                    item.get("exempt_role")
                    or item.get("wrapper")
                    or function_id in trivial_ids
                ),
            }
    for function_id in trivial_ids:
        metadata.setdefault(function_id, {"_trivial": True})
    return metadata


def old_is_trivial(function_id, metadata):
    return bool(metadata.get(function_id, {}).get("_trivial"))


def old_edge_is_cross_module(caller, callee, metadata):
    caller_module = metadata.get(caller, {}).get("module")
    callee_module = metadata.get(callee, {}).get("module")
    return bool(caller_module and callee_module and caller_module != callee_module)


def old_visit_key(edge, metadata):
    callee = metadata.get(edge.get("callee"), {})
    caller = metadata.get(edge.get("caller"), {})
    return (
        str(caller.get("path") or edge.get("caller", "").split("::", 1)[0]),
        edge.get("site_line") or edge.get("line") or 0,
        str(callee.get("path") or (edge.get("callee") or "").split("::", 1)[0]),
        callee.get("line") or 0,
        str(callee.get("name") or edge.get("name") or ""),
    )


def old_graph(edges, metadata):
    adjacency = defaultdict(list)
    opaque = defaultdict(int)
    for edge in sorted(edges, key=lambda item: old_visit_key(item, metadata)):
        caller = edge.get("caller")
        callee = edge.get("callee")
        kind = edge.get("kind", "resolved")
        if not caller:
            continue
        if kind in _OPAQUE_KINDS:
            opaque[caller] += 1
        elif kind == "resolved" and callee:
            adjacency[caller].append((callee, old_is_trivial(callee, metadata)))
    return adjacency, opaque


def old_longest_depth(
    edges, function_id, hop_limit, expansion_cap, metadata, *, allow_cross
):
    adjacency, opaque = old_graph(edges, metadata)
    stack = [(function_id, frozenset({function_id}), 0, False)]
    best = 0
    expansions = 0
    capped = False

    while stack:
        node, path, depth, crossed = stack.pop()
        node_depth = depth + bool(opaque[node])
        if node_depth > hop_limit:
            node_depth = hop_limit
            capped = True
        if not allow_cross or crossed:
            best = max(best, node_depth)

        candidates = []
        for target, trivial in adjacency[node]:
            if target in path:
                continue
            is_cross = old_edge_is_cross_module(node, target, metadata)
            if is_cross and not allow_cross:
                continue
            next_depth = depth + (not trivial)
            if next_depth > hop_limit:
                capped = True
                best = max(best, hop_limit)
                continue
            candidates.append((target, trivial, crossed or is_cross))

        if depth >= hop_limit:
            if any(not trivial for _, trivial, _ in candidates):
                capped = True
            candidates = [item for item in candidates if item[1]]

        for target, trivial, next_crossed in reversed(candidates):
            if expansions >= expansion_cap:
                capped = True
                best = max(best, hop_limit)
                stack.clear()
                break
            expansions += 1
            stack.append(
                (
                    target,
                    path | {target},
                    depth + (not trivial),
                    next_crossed,
                )
            )

    return min(best, hop_limit), capped


def old_chain_depth(
    edges, function_id, H, expansion_cap, *, facts=None, trivial_ids=()
):
    """Return longest simple in-module depth and whether a deterministic cap hit."""
    metadata = old_function_metadata(facts, trivial_ids)
    return old_longest_depth(
        edges, function_id, H, expansion_cap, metadata, allow_cross=False
    )


def old_cross_module_depth(edges, function_id, H, *, facts=None, trivial_ids=()):
    """Report longest bounded simple path containing a cross-module edge.

    The count includes non-trivial in-module hops before and after crossing; it
    is reported separately and never included in ``old_chain_depth``.
    """
    metadata = old_function_metadata(facts, trivial_ids)
    depth, _ = old_longest_depth(
        edges,
        function_id,
        H,
        max(1, len(edges) * max(H, 1)),
        metadata,
        allow_cross=True,
    )
    return depth


def old_distinct_callees(edges, function_id, *, facts=None, trivial_ids=()):
    """Count unique resolved in-module, non-trivial project callees."""
    metadata = old_function_metadata(facts, trivial_ids)
    return len(
        {
            edge["callee"]
            for edge in edges
            if edge.get("caller") == function_id
            and edge.get("kind", "resolved") == "resolved"
            and edge.get("callee")
            and not old_is_trivial(edge["callee"], metadata)
            and not old_edge_is_cross_module(function_id, edge["callee"], metadata)
        }
    )


def old_fan_out(edges, function_id, *, facts=None, trivial_ids=()):
    """Count distinct resolved callees plus each opaque or ambiguous call."""
    resolved = old_distinct_callees(
        edges, function_id, facts=facts, trivial_ids=trivial_ids
    )
    return resolved + sum(
        1
        for edge in edges
        if edge.get("caller") == function_id and edge.get("kind") in _OPAQUE_KINDS
    )


def _synthetic(n_functions, n_edges, seed=7):
    rng = random.Random(seed)  # noqa: S311
    facts = [
        {
            "id": f"f{i % 4}.cs::F{i}",
            "path": f"f{i % 4}.cs",
            "name": f"F{i}",
            "line": i,
            "module": "m1" if i % 5 else "m2",
            "wrapper": i % 11 == 0,
        }
        for i in range(n_functions)
    ]
    ids = [item["id"] for item in facts]
    kinds = ["resolved"] * 8 + ["opaque", "ambiguous"]
    edges = [
        {
            "caller": rng.choice(ids),
            "callee": rng.choice(ids),
            "kind": rng.choice(kinds),
            "site_line": rng.randrange(500),
            "name": "x",
        }
        for _ in range(n_edges)
    ]
    return facts, edges


def test_prepared_graph_matches_old_implementation():
    facts, edges = _synthetic(60, 400)
    graph = depth_graph(edges, facts)
    for item in facts[:25]:
        function_id = item["id"]
        assert chain_depth(
            edges, function_id, 6, 5000, facts=facts, graph=graph
        ) == old_chain_depth(edges, function_id, 6, 5000, facts=facts)
        assert cross_module_depth(
            edges, function_id, 6, facts=facts, graph=graph
        ) == old_cross_module_depth(edges, function_id, 6, facts=facts)
        assert chain_depth(edges, function_id, 6, 5000, facts=facts) == old_chain_depth(
            edges, function_id, 6, 5000, facts=facts
        )


def test_prepared_graph_scales_with_many_edges():
    facts, edges = _synthetic(300, 20000)
    graph = depth_graph(edges, facts)
    started = time.perf_counter()
    for item in facts[:100]:
        chain_depth(edges, item["id"], 3, 200, facts=facts, graph=graph)
    assert time.perf_counter() - started < 5
