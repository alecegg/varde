"""Raw per-function measurements of source files, independent of scoring.

Runs facts extraction, call resolution and the graph measures over one set of
files treated as one module, and reports the unscaled numbers for every
function regardless of the ``structure_confidence`` gate: cognitive, depth,
fan_out, fan_in (``callers_in_module``), tree_size, params, tokens, line_span,
max_nesting and the name-issue count. For Python it adds ``vague_names`` (bound
names from ``VAGUE_NAMES`` or single-letter non-loop names) and ``delegates``
(the whole body is one call, a docstring ignored) per function, and per file
``delegation_share`` (exact) and ``tokens_p50``; other languages report ``None``
for those. Per-measure min/median/max summarize each set. No score, no
calibration, no model call; the result is deterministic.
"""

from __future__ import annotations

import ast
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from varde_code.complexity import function_complexities
from varde_code.extract.entity import extract_file
from varde_code.quality_pass import resolve_hook
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.measures import compute_measures
from varde_code.quality_score.file_advisories import exact_delegation_share, tokens_p50

MEASURES = (
    "cognitive",
    "depth",
    "fan_out",
    "fan_in",
    "tree_size",
    "params",
    "tokens",
    "line_span",
    "max_nesting",
    "name_issues",
    "vague_names",
)
# Equal to code/bench/quality-corpus/tools/quality_degrade.VAGUE
# (a test keeps them equal).
VAGUE_NAMES = frozenset(
    ("data", "tmp", "val", "res", "obj", "item", "info", "thing", "stuff")
)
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE_NODES = (*FUNCTION_NODES, ast.Lambda, ast.ClassDef)
MODULE = "."
CONFIDENCE_ORDER = ("low", "normal")  # worst first


def max_nesting_by_line(path: str, text: str, language: str) -> dict[int, int]:
    """Deepest control-flow nesting of the functions starting on each line."""
    nesting: dict[int, int] = {}
    entities = extract_file(path, text, language).entities
    for item in function_complexities(entities):
        line = item.span.start_line
        nesting[line] = max(nesting.get(line, 0), item.max_nesting)
    return nesting


def _own_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Nodes of the function body, not descending into nested scopes."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        found.append(node)
        if not isinstance(node, SCOPE_NODES):
            stack.extend(ast.iter_child_nodes(node))
    return found


def _store_names(target: ast.AST) -> set[str]:
    return {
        n.id
        for n in ast.walk(target)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }


def vague_name_count(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Distinct bound names that are in ``VAGUE_NAMES`` or single-letter non-loop."""
    args = function.args
    bound = {
        a.arg
        for a in (
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            args.vararg,
            args.kwarg,
        )
        if a is not None
    }
    loop: set[str] = set()
    for node in _own_nodes(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
            loop |= _store_names(node.target)
    single = {n for n in bound - loop if len(n) == 1 and n != "_"}
    return len((bound & VAGUE_NAMES) | single)


def body_is_one_call(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The body, docstring ignored, is one expression or return statement of a call."""
    body = list(function.body)
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Expr | ast.Return):
        return False
    value = body[0].value
    if isinstance(value, ast.Await):
        value = value.value
    return isinstance(value, ast.Call)


def _methods_of_subclasses(tree: ast.AST) -> set[ast.AST]:
    """Functions defined directly in a class that names a base: override candidates."""
    return {
        member
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.bases
        for member in cls.body
        if isinstance(member, FUNCTION_NODES)
    }


def is_hook(
    node: ast.FunctionDef | ast.AsyncFunctionDef, overrides: set[ast.AST]
) -> bool:
    """A function others call by contract, so inlining it is not an option.

    Decorated (property, classmethod, callback), dunder, ``main``, a method of a
    subclass (a possible override) or a ``super()`` call.
    """
    name = node.name
    dunder = name.startswith("__") and name.endswith("__")
    super_call = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "super"
        for n in ast.walk(node)
    )
    return bool(
        node.decorator_list
        or dunder
        or name == "main"
        or node in overrides
        or super_call
    )


def python_function_facts(text: str) -> dict[int, dict[str, Any]]:
    """``vague_names``, ``delegates`` and ``hook`` of each Python function by line.

    A decorated function is keyed by its first decorator line and its ``def`` line.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError:
        return {}
    found: dict[int, dict[str, Any]] = {}
    overrides = _methods_of_subclasses(tree)
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_NODES):
            continue
        facts = {
            "vague_names": vague_name_count(node),
            "delegates": body_is_one_call(node),
            "hook": is_hook(node, overrides),
        }
        for line in {node.lineno, *(d.lineno for d in node.decorator_list)}:
            found[line] = facts
    return found


def function_row(
    function: Mapping[str, Any],
    measured: Mapping[str, Any],
    nesting: Mapping[int, int],
    path: str,
    python_facts: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    line, end_line = function.get("line"), function.get("end_line")
    span = (
        end_line - line + 1
        if isinstance(line, int) and isinstance(end_line, int)
        else None
    )
    own = (python_facts or {}).get(line, {}) if isinstance(line, int) else {}
    return {
        "path": path,
        "id": function["id"],
        "name": function["name"],
        "cognitive": function.get("cognitive"),
        "depth": measured.get("depth"),
        "fan_out": measured.get("fan_out"),
        "fan_in": measured.get("callers_in_module"),
        "tree_size": measured.get("tree_size"),
        "params": function.get("params"),
        "tokens": function.get("tokens"),
        "line_span": span,
        "max_nesting": nesting.get(line) if isinstance(line, int) else None,
        "name_issues": len(function.get("name_issues") or ()),
        "vague_names": own.get("vague_names"),
        "delegates": own.get("delegates"),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """Min, median and max of each measure over the rows that have a value."""
    summary: dict[str, dict[str, Any] | None] = {}
    for name in MEASURES:
        values = [row[name] for row in rows if row[name] is not None]
        summary[name] = (
            {
                "min": min(values),
                "median": statistics.median(values),
                "max": max(values),
            }
            if values
            else None
        )
    return summary


def worst_confidence(confidences: Sequence[str]) -> str | None:
    known = [c for c in confidences if c in CONFIDENCE_ORDER]
    return min(known, key=CONFIDENCE_ORDER.index) if known else None


def total_coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    total = {"resolved": 0, "ambiguous": 0, "opaque": 0, "external": 0}
    for record in records:
        for kind in total:
            total[kind] += int((record.get("call_coverage") or {}).get(kind, 0))
    return total


def raw_measure_sources(sources: Mapping[str, bytes], language: str) -> dict[str, Any]:
    """Raw measurements of ``{relative path: source bytes}`` as one module."""
    texts = {p: raw.decode("utf-8-sig", errors="replace") for p, raw in sources.items()}
    facts = {p: extract_facts(sources[p], language, p) for p in sorted(sources)}
    context = resolve_hook.prepare(sorted(facts), facts)
    edges = {p: resolve_hook.edges_for_file(context, p) for p in sorted(facts)}
    per_file = compute_measures(facts, edges, dict.fromkeys(facts, MODULE))
    rows = []
    file_rows: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(facts):
        nesting = max_nesting_by_line(path, texts[path], language)
        python_facts = (
            python_function_facts(texts[path]) if language == "python" else {}
        )
        measured = per_file[path]["functions"]
        file_rows[path] = [
            function_row(f, measured.get(str(f["id"]), {}), nesting, path, python_facts)
            for f in facts[path]["functions"]
        ]
        rows.extend(file_rows[path])
    records = [per_file[p] for p in sorted(facts)]
    return {
        "language": language,
        "files": len(facts),
        "functions": rows,
        "summary": summarize(rows),
        "file_measures": {
            p: {
                "delegation_share": exact_delegation_share(r),
                "tokens_p50": tokens_p50(r),
            }
            for p, r in file_rows.items()
        },
        "structure_confidence": worst_confidence(
            [str(r["structure_confidence"]) for r in records]
        ),
        "file_structure_confidence": {
            p: per_file[p]["structure_confidence"] for p in sorted(facts)
        },
        "call_coverage": total_coverage(records),
    }
