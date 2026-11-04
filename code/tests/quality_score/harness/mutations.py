"""Small facts-record mutations for scorer calibration constraints."""

from copy import deepcopy
from typing import Any

Facts = dict[str, Any]


def _copy(facts: Facts) -> Facts:
    return deepcopy(facts)


def rename_to_short_names(facts: Facts) -> Facts:
    """Represent short, low-information names in each function's facts."""
    changed = _copy(facts)
    for function in changed["functions"]:
        function["name_issues"] = sorted(
            set(function.get("name_issues", ())) | {"single_char", "vague"}
        )
    return changed


def nest(facts: Facts, levels: int = 1) -> Facts:
    changed = _copy(facts)
    for function in changed["functions"]:
        function["cognitive"] = function.get("cognitive", 0) + levels * 2
        function["depth"] = (function.get("depth") or 0) + levels
    return changed


def grow(facts: Facts, copies: int = 1) -> Facts:
    changed = _copy(facts)
    extra_tokens = max(1, copies) * 12
    changed["tokens"] += extra_tokens
    for function in changed["functions"]:
        function["tokens"] += extra_tokens
        function["cognitive"] = function.get("cognitive", 0) + max(1, copies)
    return changed


def add_branches(facts: Facts, branches: int = 1) -> Facts:
    changed = _copy(facts)
    for function in changed["functions"]:
        function["cognitive"] = function.get("cognitive", 0) + max(1, branches) * 2
        function["fan_out"] = (function.get("fan_out") or 0) + max(1, branches)
    return changed


def fragment(facts: Facts, count: int, *, piece_tokens: int = 20) -> Facts:
    """Append single-use, same-file helper facts; keep every original function."""
    changed = _copy(facts)
    original = changed["functions"][0]
    helpers = [
        {
            **original,
            "id": f"{original['id']}::helper-{index}",
            "line": original.get("line", 1) + index,
            "tokens": piece_tokens,
            "cognitive": max(0, original.get("cognitive", 0) // count),
            "depth": (original.get("depth") or 0) + 1,
            "fan_out": 1,
            "tree_size": 1,
            "fragment_scope": "file",
            "name_issues": [],
        }
        for index in range(count)
    ]
    changed["functions"] = [*changed["functions"], *helpers]
    changed["tokens"] += count * piece_tokens
    return changed


def forwarder_chain(facts: Facts, count: int) -> Facts:
    """Add tiny, single-caller forwarding functions to a file."""
    changed = _copy(facts)
    template = changed["functions"][0]
    changed["functions"].extend(
        {
            **template,
            "id": f"{template['id']}::forwarder-{index}",
            "tokens": 8,
            "cognitive": 0,
            "params": 1,
            "depth": max(1, count - index),
            "fan_out": 1,
            "tree_size": count - index + 1,
            "fragment_scope": "file",
            "name_issues": [],
        }
        for index in range(count)
    )
    changed["tokens"] += count * 8
    return changed


def agent_tree(facts: Facts, count: int, *, padded: bool = False) -> Facts:
    """Replace the function with a shallow or deep single-caller helper tree."""
    changed = _copy(facts)
    original = changed["functions"][0]
    helper_tokens = 50 if padded else 8
    changed["functions"] = [
        {
            **original,
            "id": f"{original['id']}::tree-{index}",
            "line": original.get("line", 1) + index,
            "tokens": helper_tokens,
            "cognitive": 0,
            "depth": 3,
            "fan_out": 3,
            "tree_size": count,
            "fragment_scope": "file",
            "name_issues": [],
        }
        for index in range(count)
    ]
    changed["tokens"] = max(changed["tokens"], count * helper_tokens)
    return changed


def inline_helper(facts: Facts) -> Facts:
    """Remove the final trivial helper and fold its tokens into the first."""
    changed = _copy(facts)
    if len(changed["functions"]) < 2:
        return changed
    helper = changed["functions"].pop()
    changed["functions"][0]["tokens"] += helper.get("tokens", 0)
    return changed


def flatten(facts: Facts, helpers: int = 3) -> Facts:
    """Merge up to `helpers` single-use same-file helpers into the first function.

    Models inlining the helpers of well-structured code: the helpers disappear
    and their tokens and cognitive load move into the caller.
    """
    changed = _copy(facts)
    functions = changed["functions"]
    merged = [
        function
        for function in functions[1:]
        if function.get("fragment_scope") == "file"
    ][:helpers]
    merged_ids = {function["id"] for function in merged}
    functions[0]["tokens"] += sum(function["tokens"] for function in merged)
    functions[0]["cognitive"] = functions[0].get("cognitive", 0) + sum(
        function.get("cognitive", 0) for function in merged
    )
    changed["functions"] = [
        function for function in functions if function["id"] not in merged_ids
    ]
    return changed


def back_edge(
    edges: list[dict[str, Any]], chain: list[str], *, site_line: int = 10_000
) -> list[dict[str, Any]]:
    """Add one call from the last function of `chain` back to its first.

    The new edge is a resolved call, as one in a dead branch still is; it closes
    a cycle through the chain and must not change the chain start's measures.
    """
    changed = deepcopy(edges)
    changed.append(
        {
            "caller": chain[-1],
            "callee": chain[0],
            "kind": "resolved",
            "site_line": site_line,
        }
    )
    return changed


def formatting_only(facts: Facts) -> Facts:
    """Formatting does not change any facts available to the scorer."""
    return _copy(facts)
