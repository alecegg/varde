"""Depth and fan-out measures over contract-shaped call edges."""

from collections import defaultdict

_OPAQUE_KINDS = {"ambiguous", "opaque"}


def _function_metadata(facts, trivial_ids=()):
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


def _is_trivial(function_id, metadata):
    return bool(metadata.get(function_id, {}).get("_trivial"))


def _edge_is_cross_module(caller, callee, metadata):
    caller_module = metadata.get(caller, {}).get("module")
    callee_module = metadata.get(callee, {}).get("module")
    return bool(caller_module and callee_module and caller_module != callee_module)


def _visit_key(edge, metadata):
    callee = metadata.get(edge.get("callee"), {})
    caller = metadata.get(edge.get("caller"), {})
    return (
        str(caller.get("path") or edge.get("caller", "").split("::", 1)[0]),
        edge.get("site_line") or edge.get("line") or 0,
        str(callee.get("path") or (edge.get("callee") or "").split("::", 1)[0]),
        callee.get("line") or 0,
        str(callee.get("name") or edge.get("name") or ""),
    )


def _graph(edges, metadata):
    adjacency = defaultdict(list)
    opaque = defaultdict(int)
    for edge in sorted(edges, key=lambda item: _visit_key(item, metadata)):
        caller = edge.get("caller")
        callee = edge.get("callee")
        kind = edge.get("kind", "resolved")
        if not caller:
            continue
        if kind in _OPAQUE_KINDS:
            opaque[caller] += 1
        elif kind == "resolved" and callee:
            adjacency[caller].append((callee, _is_trivial(callee, metadata)))
    return adjacency, opaque


def depth_graph(edges, facts=None, trivial_ids=()):
    """Prepare the sorted adjacency once so per-function calls can reuse it."""
    metadata = _function_metadata(facts, trivial_ids)
    adjacency, opaque = _graph(edges, metadata)
    return adjacency, opaque, metadata


def _longest_depth(
    edges, function_id, hop_limit, expansion_cap, prepared, *, allow_cross
):
    adjacency, opaque, metadata = prepared
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
            is_cross = _edge_is_cross_module(node, target, metadata)
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


def chain_depth(  # noqa: PLR0913 - prepared graph is an optional keyword
    edges, function_id, H, expansion_cap, *, facts=None, trivial_ids=(), graph=None
):
    """Return longest simple in-module depth and whether a deterministic cap hit."""
    prepared = graph or depth_graph(edges, facts, trivial_ids)
    return _longest_depth(
        edges, function_id, H, expansion_cap, prepared, allow_cross=False
    )


def cross_module_depth(
    edges, function_id, H, *, facts=None, trivial_ids=(), graph=None
):
    """Report longest bounded simple path containing a cross-module edge.

    The count includes non-trivial in-module hops before and after crossing; it
    is reported separately and never included in ``chain_depth``.
    """
    prepared = graph or depth_graph(edges, facts, trivial_ids)
    depth, _ = _longest_depth(
        edges,
        function_id,
        H,
        max(1, len(edges) * max(H, 1)),
        prepared,
        allow_cross=True,
    )
    return depth


def distinct_callees(edges, function_id, *, facts=None, trivial_ids=()):
    """Count unique resolved in-module, non-trivial project callees."""
    metadata = _function_metadata(facts, trivial_ids)
    return len(
        {
            edge["callee"]
            for edge in edges
            if edge.get("caller") == function_id
            and edge.get("kind", "resolved") == "resolved"
            and edge.get("callee")
            and not _is_trivial(edge["callee"], metadata)
            and not _edge_is_cross_module(function_id, edge["callee"], metadata)
        }
    )


def fan_out(edges, function_id, *, facts=None, trivial_ids=()):
    """Count distinct resolved callees plus each opaque or ambiguous call."""
    resolved = distinct_callees(
        edges, function_id, facts=facts, trivial_ids=trivial_ids
    )
    return resolved + sum(
        1
        for edge in edges
        if edge.get("caller") == function_id and edge.get("kind") in _OPAQUE_KINDS
    )
