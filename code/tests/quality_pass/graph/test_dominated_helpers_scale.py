"""Scale and equivalence tests for dominated_private_helpers."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from types import SimpleNamespace

from varde_code.quality_pass.graph import dominated_private_helpers
from varde_code.rules.pattern import _tree_sitter_node

# --- Reference: the previous per-root fixpoint implementation, kept verbatim. ---


def _old_same_module(caller, callee, facts):
    caller_module = facts.get(caller, {}).get("module")
    callee_module = facts.get(callee, {}).get("module")
    return not caller_module or not callee_module or caller_module == callee_module


def _old_dominators_from_entries(nodes, predecessors, entries):
    reached = set()
    seeded_entries = set(entries)
    while len(reached) < len(nodes):
        pending = deque(sorted(seeded_entries - reached))
        while pending:
            node = pending.popleft()
            if node in reached:
                continue
            reached.add(node)
            pending.extend(
                sorted(
                    successor
                    for successor in nodes
                    if node in predecessors[successor] and successor not in reached
                )
            )
        if len(reached) == len(nodes):
            break
        seeded_entries.add(min(nodes - reached))

    dominators = {
        node: ({node} if node in seeded_entries else set(nodes)) for node in nodes
    }
    changed = True
    while changed:
        changed = False
        for node in sorted(nodes - seeded_entries):
            parents = predecessors[node]
            common = set.intersection(*(dominators[parent] for parent in parents))
            updated = {node} | common
            if updated != dominators[node]:
                dominators[node] = updated
                changed = True
    return dominators


def _old_dominated_private_helpers(edges, facts):
    """Count non-exempt private functions dominated by each function.

    Resolved wrapper and exempt-role nodes stay in the graph so descendants
    remain reachable, but only non-exempt private functions are counted.
    """
    function_facts = {item["id"]: item for item in facts if item.get("id")}
    nodes_by_module = defaultdict(set)
    for function_id, item in function_facts.items():
        nodes_by_module[item.get("module")].add(function_id)

    predecessors = defaultdict(set)
    for edge in edges:
        caller = edge.get("caller")
        callee = edge.get("callee")
        if (
            edge.get("kind", "resolved") == "resolved"
            and caller in function_facts
            and callee in function_facts
            and _old_same_module(caller, callee, function_facts)
        ):
            predecessors[callee].add(caller)

    dominators_by_root = {}
    for nodes in nodes_by_module.values():
        module_predecessors = {node: predecessors[node] & nodes for node in nodes}
        entries = {node for node in nodes if not module_predecessors[node]}
        for root in sorted(nodes):
            dominators_by_root[root] = _old_dominators_from_entries(
                nodes, module_predecessors, entries | {root}
            )

    private = {
        function_id
        for function_id, item in function_facts.items()
        if item.get("file_private") and not item.get("exempt_role")
    }
    return {
        root: sum(
            1
            for helper in private
            if helper != root and root in dominators_by_root[root].get(helper, set())
        )
        for root in sorted(function_facts)
    }


# --- Tests ---


def _facts(n):
    return [
        {"id": f"f{i}", "file_private": i % 2 == 0, "exempt_role": None, "module": "m"}
        for i in range(n)
    ]


def _edges(n, count, seed):
    state = seed * 2654435761 + 1
    values = []
    for _ in range(count * 2):
        state = (state * 1103515245 + 12345) % (2**31)
        values.append(state // 7 % n)
    return [
        {"caller": f"f{values[2 * i]}", "callee": f"f{values[2 * i + 1]}"}
        for i in range(count)
    ]


def test_dominated_helpers_matches_reference_on_generated_graphs():
    for seed in range(40):
        edges, facts = _edges(12, 14, seed), _facts(12)
        assert dominated_private_helpers(
            edges, facts
        ) == _old_dominated_private_helpers(edges, facts)


def test_dominated_helpers_scales_to_large_module():
    n = 1500
    start = time.monotonic()
    dominated_private_helpers(_edges(n, 3000, 1), _facts(n))
    assert time.monotonic() - start < 20


def _span_node(start, end, children=()):
    return SimpleNamespace(start_byte=start, end_byte=end, children=list(children))


def test_tree_sitter_node_skips_subtrees_outside_span():
    visited = []

    class Leaf(SimpleNamespace):
        @property
        def children(self):
            visited.append(self.start_byte)
            return []

    leaves = [Leaf(start_byte=i * 2, end_byte=i * 2 + 1) for i in range(20000)]
    root = _span_node(0, 40000, leaves)
    found = _tree_sitter_node(root, 39998, 39999)
    assert found is leaves[-1]
    assert visited == [39998]
