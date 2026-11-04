"""Pure helpers for validating the P+D2 scorer candidate on unseen modules.

False-positive set: tidy few-function modules, picked by content hash.
Mechanical monoliths: every function of a real multi-function module merged
into one function (behaviour is not preserved; the code only has to parse).
No model call.
"""

from __future__ import annotations

import ast
import hashlib
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from typing import Any

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)
VAGUE_NAMES = {"foo", "bar", "baz", "temp", "tmp", "data", "stuff", "thing", "func"}
FP_MAX_FUNCTIONS = 3
MONOLITH_MIN_FUNCTIONS = 4


def content_key(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def pick_by_hash(
    candidates: Mapping[str, tuple[str, bytes]], count: int, per_origin: int
) -> list[str]:
    """Keys of the first ``count`` candidates by content hash, at most
    ``per_origin`` from one origin (value is ``(origin, source)``)."""
    taken: dict[str, int] = {}
    chosen: list[str] = []
    for key in sorted(candidates, key=lambda k: content_key(candidates[k][1])):
        origin = candidates[key][0]
        if len(chosen) == count:
            break
        if taken.get(origin, 0) >= per_origin:
            continue
        taken[origin] = taken.get(origin, 0) + 1
        chosen.append(key)
    return chosen


def all_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, FUNCTION_NODES)]


def decent_names(names: Sequence[str]) -> bool:
    return all(len(n) >= 4 and n not in VAGUE_NAMES for n in names)


def is_tidy_few_function(source: str) -> bool:
    """1-3 functions with decent names; no cognitive or size filter, so the
    scorer's own signal cannot pick its own false-positive test set."""
    try:
        funcs = all_functions(ast.parse(source))
    except SyntaxError:
        return False
    if not 1 <= len(funcs) <= FP_MAX_FUNCTIONS:
        return False
    return decent_names([f.name for f in funcs])


def max_nesting(source: str) -> int:
    """Deepest nesting of branching statements inside any function."""

    def depth(node: ast.AST) -> int:
        inner = max((depth(c) for c in ast.iter_child_nodes(node)), default=0)
        return inner + isinstance(node, BRANCH_NODES)

    return max((depth(f) for f in all_functions(ast.parse(source))), default=0)


def has_nested_definition(func: ast.AST) -> bool:
    inner = (n for n in ast.walk(func) if n is not func)
    return any(isinstance(n, (*FUNCTION_NODES, ast.ClassDef)) for n in inner)


def module_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Top-level functions and class methods, in source order."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, FUNCTION_NODES):
            found.append(node)
        if isinstance(node, ast.ClassDef):
            found += [n for n in node.body if isinstance(n, FUNCTION_NODES)]
    return found


def parameter_names(
    funcs: Sequence[ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[str]:
    names: dict[str, None] = {}
    for func in funcs:
        a = func.args
        every = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
        names.update({x.arg: None for x in every if x is not None})
    return list(names)


def body_without_docstring(func: ast.AST) -> list[ast.stmt]:
    body = list(func.body)  # type: ignore[attr-defined]
    first = body[0]
    is_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    return body[1:] if is_doc and isinstance(first.value.value, str) else body  # type: ignore[attr-defined]


def inline_to_monolith(source: str) -> str | None:
    """One function holding every function body of the module, or None when the
    module has fewer than ``MONOLITH_MIN_FUNCTIONS`` nest-free functions."""
    tree = ast.parse(source)
    funcs = [f for f in module_functions(tree) if not has_nested_definition(f)]
    if len(funcs) < MONOLITH_MIN_FUNCTIONS:
        return None
    header_kinds = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)
    header = [n for n in tree.body if isinstance(n, header_kinds)]
    body = [s for f in funcs for s in body_without_docstring(f)]
    if not body:
        return None
    params = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg=n) for n in parameter_names(funcs)],
        kwonlyargs=[],
        kw_defaults=[],
        defaults=[ast.Constant(None)] * len(parameter_names(funcs)),
    )
    is_async = any(isinstance(f, ast.AsyncFunctionDef) for f in funcs)
    kind = ast.AsyncFunctionDef if is_async else ast.FunctionDef
    mono = kind(
        name="process_module", args=params, body=body, decorator_list=[], returns=None
    )
    module = ast.Module(body=[*header, mono], type_ignores=[])
    code = ast.unparse(ast.fix_missing_locations(module))
    ast.parse(code)
    return code


def cut_bootstrap(
    good: Sequence[float], cut: Callable[[Sequence[float]], float], rounds: int = 500
) -> dict[str, float]:
    """Spread of the cut line when the good set is resampled (seeded)."""
    rng = random.Random(0)  # noqa: S311 (seeded resampling)
    cuts = [cut([rng.choice(good) for _ in good]) for _ in range(rounds)]
    return {
        "mean": statistics.fmean(cuts),
        "sd": statistics.pstdev(cuts),
        "min": min(cuts),
        "max": max(cuts),
    }


def metric_poor(row: Mapping[str, Any]) -> bool:
    """Plausibly poor by raw metrics (not by the scorer's cost model)."""
    return row["max_cognitive"] >= 15 or row["nesting"] >= 4 or row["max_tokens"] >= 400


def metric_clean(row: Mapping[str, Any]) -> bool:
    """Clearly tidy by raw metrics: cognitive within the comfort 10, shallow, short."""
    return (
        row["max_cognitive"] <= 10 and row["nesting"] <= 2 and row["max_tokens"] <= 300
    )
