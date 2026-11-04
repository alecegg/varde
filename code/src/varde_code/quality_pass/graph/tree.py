"""Dominated helper counts for module-local call graphs."""

from collections import defaultdict, deque


def _same_module(caller, callee, facts):
    caller_module = facts.get(caller, {}).get("module")
    callee_module = facts.get(callee, {}).get("module")
    return not caller_module or not callee_module or caller_module == callee_module


def _sorted_successors(nodes, predecessors):
    successors = {node: [] for node in nodes}
    for successor in sorted(nodes):
        for node in predecessors[successor]:
            successors[node].append(successor)
    return successors


def _seeded_entries(nodes, successors, entries):
    """Entries plus one smallest unreached node per unreachable component."""
    reached = set()
    seeded_entries = set(entries)
    while len(reached) < len(nodes):
        pending = deque(sorted(seeded_entries - reached))
        while pending:
            node = pending.popleft()
            if node in reached:
                continue
            reached.add(node)
            pending.extend(s for s in successors[node] if s not in reached)
        if len(reached) == len(nodes):
            break
        seeded_entries.add(min(nodes - reached))
    return seeded_entries


def _dominated_by(root, nodes, successors, seeded_entries):
    """Nodes whose every path from the seeded entries passes through root."""
    reached = set()
    pending = deque(seeded_entries - {root})
    while pending:
        node = pending.popleft()
        if node in reached or node == root:
            continue
        reached.add(node)
        pending.extend(successors[node])
    return nodes - reached - {root}


def dominated_private_helpers(edges, facts):
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
            and _same_module(caller, callee, function_facts)
        ):
            predecessors[callee].add(caller)

    dominated_by_root = {}
    for nodes in nodes_by_module.values():
        module_predecessors = {node: predecessors[node] & nodes for node in nodes}
        successors = _sorted_successors(nodes, module_predecessors)
        entries = {node for node in nodes if not module_predecessors[node]}
        for root in sorted(nodes):
            seeded = _seeded_entries(nodes, successors, entries | {root})
            dominated_by_root[root] = _dominated_by(root, nodes, successors, seeded)

    private = {
        function_id
        for function_id, item in function_facts.items()
        if item.get("file_private") and not item.get("exempt_role")
    }
    return {
        root: sum(1 for helper in private if helper in dominated_by_root[root])
        for root in sorted(function_facts)
    }
