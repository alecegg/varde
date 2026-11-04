"""L3 graph measures assembled from L2 edges and L1 function facts.

Measures stay in one module per call graph, matching the architecture's
"edges of the file and of the files of its module" scope. Every traversal is
bounded by a deterministic expansion counter derived from the input size, so
no wall clock ever enters a result.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from varde_code.quality_pass.graph import (
    chain_depth,
    cross_module_depth,
    depth_graph,
    distinct_callees,
    dominated_private_helpers,
    fan_out,
)
from varde_code.quality_pass.graph.fragments import fragment_counts
from varde_code.quality_pass.pass_.keys import H_HOPS, blake2b_digest, canonical_json

DEFAULT_T_FRAG = 60
_EXPANSION_FACTOR = 8
_MIN_EXPANSION_CAP = 64
_OPAQUE_KINDS = {"ambiguous", "opaque"}
_COVERAGE_KINDS = ("resolved", "ambiguous", "opaque", "external")


def tree_size(
    edges: Iterable[Mapping[str, Any]],
    function_id: str,
    hop_limit: int,
    expansion_cap: int,
    *,
    facts: Sequence[Mapping[str, Any]] = (),
    trivial_ids: Iterable[str] = (),
) -> int:
    """Count distinct non-trivial project callees within ``hop_limit`` hops.

    Trivial (exempt-role) nodes are traversed but add no hop, mirroring the
    depth rule in ``quality_pass.graph``. Cross-module edges are skipped.
    """
    adjacency, modules, trivial = _traversal_inputs(edges, facts, trivial_ids)
    return _count_reachable(
        adjacency, function_id, hop_limit, expansion_cap, modules, trivial
    )


def module_signatures(
    facts_by_file: Mapping[str, dict],
    edges_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    modules: Mapping[str, str],
) -> dict[str, str]:
    """Hash each module's function roles and edges for the L3 key.

    The per-hop Merkle fingerprint is forward-only; reverse measures
    (``callers_in_module``, ``fragment_scope``, ``dominated_helpers``, fragment
    counts) and the module-wide expansion cap also depend on this state.
    """
    functions_by_module: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    edges_by_module: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for path in sorted(facts_by_file):
        module = modules[path]
        functions_by_module[module].extend(facts_by_file[path]["functions"])
        edges_by_module[module].extend(edges_by_file[path])
    return {
        module: _module_signature(functions_by_module[module], edges_by_module[module])
        for module in sorted(functions_by_module)
    }


def compute_measures(
    facts_by_file: Mapping[str, dict],
    edges_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    modules: Mapping[str, str],
    *,
    tfrag: int = DEFAULT_T_FRAG,
    only_modules: set[str] | None = None,
) -> dict[str, dict]:
    """Return per-file L3 measures for the requested modules only."""
    files_by_module: dict[str, list[str]] = defaultdict(list)
    for path in sorted(facts_by_file):
        files_by_module[modules[path]].append(path)
    result: dict[str, dict] = {}
    for module in sorted(files_by_module):
        if only_modules is not None and module not in only_modules:
            continue
        result.update(
            _module_measures(
                module,
                sorted(files_by_module[module]),
                facts_by_file,
                edges_by_file,
                tfrag,
            )
        )
    return result


def _module_measures(
    module: str,
    module_files: Sequence[str],
    facts_by_file: Mapping[str, dict],
    edges_by_file: Mapping[str, Sequence[Mapping[str, Any]]],
    tfrag: int,
) -> dict[str, dict]:
    module_functions = [
        {**function, "module": module}
        for path in module_files
        for function in facts_by_file[path]["functions"]
    ]
    module_edges = [edge for path in module_files for edge in edges_by_file[path]]
    # A module-level call site has no caller function; it cannot belong to any
    # function's graph, so it is excluded from the traversals (but not from the
    # file's coverage, and the module signature above still covers it).
    traversal_edges = [edge for edge in module_edges if edge.get("caller")]
    expansion_cap = max(
        _MIN_EXPANSION_CAP,
        _EXPANSION_FACTOR * (len(module_edges) + len(module_functions)),
    )
    callers = _callers_by_function(traversal_edges)
    dominated = dominated_private_helpers(traversal_edges, module_functions)
    reverse = {
        function["id"]: {
            "callers": sorted(set(callers.get(function["id"], ()))),
            "dominated": int(dominated.get(function["id"], 0)),
        }
        for function in module_functions
    }
    unmeasured = _unmeasured_functions(module_files, facts_by_file)
    graph = depth_graph(traversal_edges, module_functions)
    per_function = {
        function["id"]: _function_measures(
            function,
            traversal_edges,
            module_functions,
            reverse,
            unmeasured,
            expansion_cap,
            graph,
        )
        for function in module_functions
    }
    return {
        path: _file_measures(
            path,
            module,
            facts_by_file[path],
            per_function,
            edges_by_file[path],
            tfrag,
        )
        for path in module_files
    }


def _function_measures(  # noqa: PLR0913, PLR0917 - one prepared graph per module
    function: Mapping[str, Any],
    module_edges: Sequence[Mapping[str, Any]],
    module_functions: Sequence[Mapping[str, Any]],
    reverse: Mapping[str, Mapping[str, Any]],
    unmeasured: set[str],
    expansion_cap: int,
    graph: tuple,
) -> dict:
    function_id = str(function["id"])
    caller_ids = [str(item) for item in reverse.get(function_id, {}).get("callers", ())]
    if function_id in unmeasured:
        return {
            "depth": None,
            "depth_capped": None,
            "fan_out": None,
            "distinct_callees": None,
            "tree_size": None,
            "cross_module_depth": None,
            "opaque_calls": None,
            "callers_in_module": len(caller_ids),
            "fragment_scope": _fragment_scope(function_id, caller_ids),
            "dominated_helpers": None,
        }
    depth, capped = chain_depth(
        module_edges,
        function_id,
        H_HOPS,
        expansion_cap,
        facts=module_functions,
        graph=graph,
    )
    return {
        "depth": depth,
        "depth_capped": capped,
        "fan_out": fan_out(module_edges, function_id, facts=module_functions),
        "distinct_callees": distinct_callees(
            module_edges, function_id, facts=module_functions
        ),
        "tree_size": tree_size(
            module_edges, function_id, H_HOPS, expansion_cap, facts=module_functions
        ),
        "cross_module_depth": cross_module_depth(
            module_edges, function_id, H_HOPS, facts=module_functions, graph=graph
        ),
        "opaque_calls": _opaque_count(module_edges, function_id),
        "callers_in_module": len(caller_ids),
        "fragment_scope": _fragment_scope(function_id, caller_ids),
        "dominated_helpers": int(reverse.get(function_id, {}).get("dominated", 0)),
    }


def _module_signature(
    functions: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> str:
    roles = sorted(
        (
            [
                str(function["id"]),
                function.get("exempt_role"),
                bool(function.get("file_private")),
            ]
            for function in functions
        ),
        key=canonical_json,
    )
    edge_rows = sorted((_edge_rows(edge) for edge in edges), key=canonical_json)
    return blake2b_digest(canonical_json([roles, edge_rows]))


def _edge_rows(edge: Mapping[str, Any]) -> list:
    return [
        edge.get("caller"),
        edge.get("site_line"),
        edge.get("callee"),
        edge.get("kind"),
        edge.get("pass"),
    ]


def _unmeasured_functions(
    module_files: Sequence[str], facts_by_file: Mapping[str, dict]
) -> set[str]:
    found: set[str] = set()
    for path in module_files:
        regions = facts_by_file[path].get("unmeasured_regions") or ()
        if not regions:
            continue
        for function in facts_by_file[path]["functions"]:
            if _intersects_region(function, regions):
                found.add(str(function["id"]))
    return found


def _intersects_region(
    function: Mapping[str, Any], regions: Sequence[Mapping[str, Any]]
) -> bool:
    line = function.get("line")
    end_line = function.get("end_line")
    if not isinstance(line, int) or not isinstance(end_line, int):
        return False
    return any(
        int(region["start_line"]) <= end_line and line <= int(region["end_line"])
        for region in regions
    )


def _file_measures(
    path: str,
    module: str,
    record: Mapping[str, Any],
    per_function: Mapping[str, dict],
    edges: Sequence[Mapping[str, Any]],
    tfrag: int,
) -> dict:
    coverage = _coverage(edges)
    functions = []
    for function in record["functions"]:
        measures = per_function[str(function["id"])]
        functions.append(
            {
                **function,
                "callers_in_module": measures["callers_in_module"],
                "fragment_scope": measures["fragment_scope"],
            }
        )
    fragment_input = [{"path": path, "functions": functions, "call_coverage": coverage}]
    counts = fragment_counts(fragment_input, tfrag)
    confidence = counts["per_file"][path]
    return {
        "path": path,
        "module": module,
        "language": record.get("language"),
        "call_coverage": coverage,
        "unresolved_share": confidence["unresolved_share"],
        "structure_confidence": confidence["structure_confidence"],
        "fragments": {"file": counts["file"], "module": counts["module"]},
        "import_fan_out": _import_fan_out(edges, confidence["structure_confidence"]),
        "functions": {
            str(function["id"]): per_function[str(function["id"])]
            for function in record["functions"]
        },
    }


def _coverage(edges: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(_COVERAGE_KINDS, 0)
    for edge in edges:
        kind = str(edge.get("kind", "resolved"))
        if kind in counts:
            counts[kind] += 1
    return counts


def _callers_by_function(
    edges: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    callers: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        callee = edge.get("callee")
        caller = edge.get("caller")
        if callee and caller:
            callers[str(callee)].append(str(caller))
    return callers


def _fragment_scope(function_id: str, caller_ids: Sequence[str]) -> str | None:
    if len(caller_ids) != 1:
        return None
    caller_file = caller_ids[0].split("::", 1)[0]
    return "file" if caller_file == function_id.split("::", 1)[0] else "module"


def _opaque_count(edges: Sequence[Mapping[str, Any]], function_id: str) -> int:
    return sum(
        1
        for edge in edges
        if edge.get("caller") == function_id and edge.get("kind") in _OPAQUE_KINDS
    )


def _import_fan_out(edges: Sequence[Mapping[str, Any]], confidence: str) -> int | None:
    if confidence != "normal":
        return None
    return len(
        {
            str(edge["callee"]).split("::", 1)[0]
            for edge in edges
            if edge.get("kind", "resolved") == "resolved" and edge.get("callee")
        }
    )


def _traversal_inputs(
    edges: Iterable[Mapping[str, Any]],
    facts: Sequence[Mapping[str, Any]],
    trivial_ids: Iterable[str],
) -> tuple[dict[str, list[str]], dict[str, str | None], set[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    modules: dict[str, str | None] = {}
    trivial = set(trivial_ids)
    for function in facts:
        function_id = str(function["id"])
        module = function.get("module")
        modules[function_id] = module if isinstance(module, str) else None
        if function.get("exempt_role"):
            trivial.add(function_id)
    for edge in edges:
        caller = edge.get("caller")
        if caller and edge.get("kind", "resolved") == "resolved" and edge.get("callee"):
            adjacency[str(caller)].append(str(edge["callee"]))
    return adjacency, modules, trivial


def _count_reachable(
    adjacency: Mapping[str, Sequence[str]],
    function_id: str,
    hop_limit: int,
    expansion_cap: int,
    modules: Mapping[str, str | None],
    trivial: set[str],
) -> int:
    best = {function_id: 0}
    reachable: set[str] = set()
    expansions = 0
    queue = deque([(function_id, 0)])
    while queue:
        node, depth = queue.popleft()
        if depth > best.get(node, hop_limit + 1):
            continue
        for target in sorted(set(adjacency.get(node, ()))):
            if modules.get(node) != modules.get(target):
                continue
            step = 0 if target in trivial else 1
            next_depth = depth + step
            if next_depth > hop_limit:
                continue
            if expansions >= expansion_cap:
                return len(reachable)
            expansions += 1
            if next_depth >= best.get(target, hop_limit + 1):
                continue
            best[target] = next_depth
            if step:
                reachable.add(target)
            queue.append((target, next_depth))
    return len(reachable)
