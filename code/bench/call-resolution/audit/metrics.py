"""Metrics and repository-cluster bootstrap intervals for audit records."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence

from audit.records import GROUND_TRUTH_SENTINELS, validate_record

EXCLUDED_RECALL_CLASSES = {"dynamic", "higher_order"}
DEPTH_SCOPES = {"module", "all"}


def compute_metrics(
    records: Sequence[Mapping[str, object]],
    class_frequencies: Mapping[str, int] | None = None,
    bootstrap_replicates: int = 1000,
    seed: int = 0,
    scope: str = "module",
) -> dict[str, object]:
    """Compute class metrics, natural-frequency recall, coverage and depth error."""
    if bootstrap_replicates < 1:
        raise ValueError("bootstrap_replicates must be positive")
    if scope not in DEPTH_SCOPES:
        raise ValueError("scope must be 'module' or 'all'")
    for record in records:
        validate_record(dict(record))
    by_class: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        by_class[str(record["call_class"])].append(record)

    per_class = {
        name: _class_metrics(items) for name, items in sorted(by_class.items())
    }
    included = {
        name: metrics["recall"]
        for name, metrics in per_class.items()
        if name not in EXCLUDED_RECALL_CLASSES and metrics["recall"] is not None
    }
    weights = _recall_weights(included, class_frequencies)
    natural_recall = sum(included[name] * weights[name] for name in included)
    repos = sorted({str(record["repo"]) for record in records})
    bootstrap = _bootstrap_intervals(
        records, repos, class_frequencies, bootstrap_replicates, seed, scope
    )
    recall_interval = bootstrap["natural_frequency_recall"]
    return {
        "per_class": per_class,
        "precision": _precision(records),
        "natural_frequency_recall": natural_recall if included else None,
        "natural_frequency_weights": weights,
        "resolved_share": _resolved_share(records),
        "unknown_sites": sum(record["ground_truth"] == "unknown" for record in records),
        "external_sites": sum(
            record["ground_truth"] == "external" for record in records
        ),
        "bootstrap_95": bootstrap,
        "recall_bootstrap_95": recall_interval,
        "depth_error": _depth_error(records, scope),
    }


def _class_metrics(
    records: Sequence[Mapping[str, object]],
) -> dict[str, float | int | None]:
    resolved = [
        record for record in records if record.get("measured_status") == "resolved"
    ]
    correct = [
        record
        for record in resolved
        if isinstance(record.get("measured_edge"), str)
        and record.get("measured_edge") == record.get("ground_truth")
    ]
    in_repo = [record for record in records if _is_target(record.get("ground_truth"))]
    return {
        "sites": len(records),
        "precision": len(correct) / len(resolved) if resolved else None,
        "recall": len(correct) / len(in_repo) if in_repo else None,
    }


def _recall_weights(
    included: Mapping[str, float | None], frequencies: Mapping[str, int] | None
) -> dict[str, float]:
    raw = {name: max(0, (frequencies or {}).get(name, 0)) for name in included}
    total = sum(raw.values())
    if total == 0:
        raw = dict.fromkeys(included, 1)
        total = len(raw)
    return {name: weight / total for name, weight in raw.items()}


def _resolved_share(records: Sequence[Mapping[str, object]]) -> float | None:
    counted = [
        record
        for record in records
        if record.get("measured_status")
        in {"resolved", "ambiguous", "opaque", "unresolved"}
    ]
    if not counted:
        return None
    resolved = sum(record.get("measured_status") == "resolved" for record in counted)
    return resolved / len(counted)


def _bootstrap_intervals(
    records: Sequence[Mapping[str, object]],
    repos: Sequence[str],
    frequencies: Mapping[str, int] | None,
    replicates: int,
    seed: int,
    scope: str,
) -> dict[str, dict[str, float] | None]:
    names = ("precision", "natural_frequency_recall", "resolved_share", "depth_error")
    if len(repos) < 2:
        return dict.fromkeys(names)
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        grouped[str(record["repo"])].append(record)
    samples: dict[str, list[float]] = defaultdict(list)
    rng = random.Random(seed)  # noqa: S311 - Deterministic statistical resampling is not cryptographic.
    for _ in range(replicates):
        sampled_repos = [rng.choice(repos) for _ in repos]
        sampled = [record for repo in sampled_repos for record in grouped[repo]]
        values = _bootstrap_values(sampled, frequencies, scope)
        for name, value in values.items():
            if value is not None:
                samples[name].append(value)
    return {
        name: _interval(values) if values else None for name, values in samples.items()
    } | {name: None for name in names if name not in samples}


def _bootstrap_values(
    records: Sequence[Mapping[str, object]],
    frequencies: Mapping[str, int] | None,
    scope: str,
) -> dict[str, float | None]:
    recall = _natural_recall(records, frequencies)
    depth = _depth_error(records, scope)["mean_absolute_error"]
    return {
        "precision": _precision(records),
        "natural_frequency_recall": recall,
        "resolved_share": _resolved_share(records),
        "depth_error": depth,
    }


def _interval(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {"lower": _quantile(ordered, 0.025), "upper": _quantile(ordered, 0.975)}


def _precision(records: Sequence[Mapping[str, object]]) -> float | None:
    resolved = [
        record for record in records if record.get("measured_status") == "resolved"
    ]
    if not resolved:
        return None
    correct = sum(
        isinstance(record.get("measured_edge"), str)
        and record.get("measured_edge") == record.get("ground_truth")
        for record in resolved
    )
    return correct / len(resolved)


def _natural_recall(
    records: Sequence[Mapping[str, object]], frequencies: Mapping[str, int] | None
) -> float | None:
    metrics = {
        name: _class_metrics(
            [record for record in records if record["call_class"] == name]
        )["recall"]
        for name in {str(record["call_class"]) for record in records}
        if name not in EXCLUDED_RECALL_CLASSES
    }
    values = {name: value for name, value in metrics.items() if value is not None}
    if not values:
        return None
    weights = _recall_weights(values, frequencies)
    return sum(float(values[name]) * weights[name] for name in values)


def _is_target(value: object) -> bool:
    return isinstance(value, str) and value not in GROUND_TRUTH_SENTINELS


def _quantile(values: Sequence[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(values) - 1)
    fraction = position - low
    return values[low] * (1 - fraction) + values[high] * fraction


def _depth_error(
    records: Sequence[Mapping[str, object]], scope: str = "module"
) -> dict[str, float | int | None]:
    functions = {str(row["function_id"]) for row in records if row.get("function_id")}
    if not functions:
        return {"functions": 0, "mean_absolute_error": None, "within_one_share": None}
    truth_edges: dict[str, set[str]] = defaultdict(set)
    measured_edges: dict[str, set[str]] = defaultdict(set)
    for row in records:
        caller = row.get("function_id")
        if not isinstance(caller, str):
            continue
        truth = row.get("ground_truth")
        measured = row.get("measured_edge")
        caller_module = row.get("module")
        if _is_target(truth) and _in_scope(
            caller_module, row.get("ground_truth_module"), scope
        ):
            truth_edges[caller].add(truth)
        if (
            row.get("measured_status") == "resolved"
            and isinstance(measured, str)
            and _in_scope(caller_module, row.get("measured_module"), scope)
        ):
            measured_edges[caller].add(measured)
    truth_depths = _graph_depths(truth_edges)
    measured_depths = _graph_depths(measured_edges)
    errors = [
        abs(truth_depths.get(function, 0) - measured_depths.get(function, 0))
        for function in sorted(functions)
    ]
    return {
        "functions": len(functions),
        "mean_absolute_error": sum(errors) / len(errors),
        "within_one_share": sum(error <= 1 for error in errors) / len(errors),
    }


def _in_scope(caller_module: object, target_module: object, scope: str) -> bool:
    return scope == "all" or (
        isinstance(caller_module, str)
        and caller_module
        and caller_module == target_module
    )


def _graph_depths(edges: Mapping[str, set[str]]) -> dict[str, int]:
    """Collapse cycles iteratively, then compute longest paths in the DAG."""
    nodes = set(edges)
    reverse: dict[str, set[str]] = defaultdict(set)
    for caller, callees in edges.items():
        nodes.update(callees)
        for callee in callees:
            reverse[callee].add(caller)
    order = _finish_order(edges, nodes)
    components, component_of = _strong_components(order, reverse)
    depth_by_component = _component_depths(edges, components, component_of)
    return {
        node: depth_by_component[component] for node, component in component_of.items()
    }


def _finish_order(edges: Mapping[str, set[str]], nodes: set[str]) -> list[str]:
    order: list[str] = []
    visited: set[str] = set()
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(sorted(edges.get(start, set()))))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                order.append(node)
                stack.pop()
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(sorted(edges.get(child, set())))))
    return order


def _strong_components(
    order: Sequence[str], reverse: Mapping[str, set[str]]
) -> tuple[list[list[str]], dict[str, int]]:
    component_of: dict[str, int] = {}
    components: list[list[str]] = []
    for start in reversed(order):
        if start in component_of:
            continue
        index = len(components)
        component = []
        stack = [start]
        component_of[start] = index
        while stack:
            node = stack.pop()
            component.append(node)
            for parent in reverse.get(node, set()):
                if parent not in component_of:
                    component_of[parent] = index
                    stack.append(parent)
        components.append(component)
    return components, component_of


def _component_depths(
    edges: Mapping[str, set[str]],
    components: Sequence[Sequence[str]],
    component_of: Mapping[str, int],
) -> dict[int, int]:
    dag: dict[int, set[int]] = defaultdict(set)
    indegree = [0] * len(components)
    for caller, callees in edges.items():
        source = component_of[caller]
        for callee in callees:
            target = component_of[callee]
            if source != target and target not in dag[source]:
                dag[source].add(target)
                indegree[target] += 1
    queue = [index for index, degree in enumerate(indegree) if degree == 0]
    topological = []
    while queue:
        component = queue.pop()
        topological.append(component)
        for child in dag.get(component, set()):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    depth_by_component: dict[int, int] = {}
    for component in reversed(topological):
        depth_by_component[component] = max(
            (depth_by_component[child] + 1 for child in dag.get(component, set())),
            default=0,
        )
    return depth_by_component
