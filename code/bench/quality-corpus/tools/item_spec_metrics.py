"""Build call graphs and summary measurements for item versions."""

from __future__ import annotations

from item_spec_extract import TOKEN, Function


def graph(functions: list[Function]) -> dict[str, list[str]]:
    """Map each function to the distinct same-file functions it calls."""
    names = {function.name for function in functions}
    return {
        function.name: sorted(
            {
                call
                for call in (
                    function.edges if function.edges is not None else function.calls
                )
                if call in names
            }
        )
        for function in functions
    }


def depth(
    calls: dict[str, list[str]], entry: str, seen: frozenset[str] = frozenset()
) -> int:
    if entry in seen:
        return 0
    return 1 + max(
        (depth(calls, child, seen | {entry}) for child in calls.get(entry, [])),
        default=0,
    )


def reachable(calls: dict[str, list[str]], entry: str) -> set[str]:
    found: set[str] = set()
    pending = [entry]
    while pending:
        node = pending.pop()
        if node in found:
            continue
        found.add(node)
        pending.extend(calls.get(node, []))
    return found


def cyclic(calls: dict[str, list[str]]) -> set[str]:
    """Return every function that takes part in a cycle, including self-calls."""
    visiting: set[str] = set()
    complete: set[str] = set()
    cycles: set[str] = set()

    def visit(node: str, path: tuple[str, ...]) -> None:
        if node in visiting:
            cycles.update(path[path.index(node) :])
            return
        if node in complete:
            return
        visiting.add(node)
        for child in calls.get(node, []):
            visit(child, (*path, child))
        visiting.remove(node)
        complete.add(node)

    for node in calls:
        visit(node, (node,))
    return cycles


def whole_file_tokens(source: str) -> int:
    """Count every token of a version source, functions and top level alike."""
    return len(TOKEN.findall(source))


def row(version: str, source: str, functions: list[Function], entry_name: str) -> str:
    calls = graph(functions)
    return (
        f"{version}: whole_file_tokens={whole_file_tokens(source)} "
        f"functions={len(functions)} "
        f"per_function={[(f.name, f.tokens, f.lines) for f in functions]} "
        f"chain={depth(calls, entry_name) if entry_name in calls else 0} "
        f"entry_fanout={len(calls.get(entry_name, []))} "
        f"cognitive={sum(f.complexity for f in functions)}"
    )
