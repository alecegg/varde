"""Conservative, syntax-checked Rust held-out mutations.

``inline-all-locals`` inlines the first safe local of each function;
``loops-to-recursion`` emits a recursive helper and can exhaust the stack on
very large slices.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import tempfile
from itertools import pairwise
from pathlib import Path

from tree_sitter import Node
from varde_code.parse import parse_source

from ..core import Mutation, make_mutation, random_for, stable_seed

OPERATORS = {
    "reorder-and-rename": "invariant",
    "inline-all-locals": "invariant",
    "add-dead-branches": "invariant",
    "wrap-in-class": "increased structural debt",
    "loops-to-recursion": "increased structural debt",
}


def rust_grammar_available() -> bool:
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        root = Path(configured)
    else:
        cache_root = Path(
            os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
        )
        root = cache_root / "grammars"
    return (
        next(root.glob("tree-sitter-language-pack/*/libs/libtree_sitter_rust.*"), None)
        is not None
    )


def mutate(
    operator: str, source: str, pair_group_id: str, seed: int | None = None
) -> Mutation:
    if operator not in OPERATORS:
        raise ValueError(f"unknown Rust mutation operator: {operator}")
    resolved_seed = stable_seed(operator, source, seed)
    rng = random_for(operator, source, resolved_seed)
    if not rust_grammar_available():
        return _result(
            source,
            operator,
            pair_group_id,
            resolved_seed,
            "Rust tree-sitter grammar is not cached; skipped without downloading",
        )
    try:
        root = parse_source("rust", source).root
    except (RuntimeError, OSError, ValueError) as exc:
        return _result(source, operator, pair_group_id, resolved_seed, str(exc))
    if root.has_error:
        raise ValueError("cannot mutate invalid Rust source")
    if operator == "wrap-in-class":
        output, reason = source, "not applicable: Rust has no class declarations"
    elif operator == "reorder-and-rename":
        output, reason = _reorder_and_rename(source, root, rng)
    elif operator == "inline-all-locals":
        output, reason = _inline_local(source, root)
    elif operator == "add-dead-branches":
        output, reason = _add_dead_branches(source, root, rng)
    else:
        output, reason = _loops_to_recursion(source, root)
    if reason is None and output == source:
        reason = "operator produced no source change"
    if reason is None and not _valid_rust(output):
        raise ValueError(f"{operator} produced invalid Rust source")
    return _result(
        source if reason else output, operator, pair_group_id, resolved_seed, reason
    )


def _result(
    source: str, operator: str, pair_group_id: str, seed: int, reason: str | None
) -> Mutation:
    return make_mutation(
        source, operator, OPERATORS[operator], pair_group_id, seed, reason
    )


def _valid_rust(source: str) -> bool:
    try:
        if parse_source("rust", source).has_error():
            return False
    except RuntimeError, OSError, ValueError:
        return False
    rustc = shutil.which("rustc")
    if rustc is None:
        return True
    with tempfile.TemporaryDirectory(prefix="varde-rust-syntax-") as temp:
        path = Path(temp) / "candidate.rs"
        path.write_text(source)
        result = subprocess.run(  # noqa: S603 - Runs the configured Rust compiler on generated source.
            [
                rustc,
                "--edition",
                "2021",
                "--crate-type",
                "lib",
                "--crate-name",
                "mutation_candidate",
                "--emit",
                "metadata",
                "-o",
                str(Path(temp) / "candidate.rmeta"),
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0


def _walk(node: Node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _text(source: str, node: Node) -> str:
    return source.encode()[node.start_byte : node.end_byte].decode()


def _edit(source: str, edits: list[tuple[int, int, str]]) -> str:
    data = source.encode()
    for start, end, replacement in sorted(edits, reverse=True):
        data = data[:start] + replacement.encode() + data[end:]
    return data.decode()


def _functions(root: Node) -> list[Node]:
    return [node for node in root.named_children if node.type == "function_item"]


def _reorder_and_rename(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions:
        return source, "no top-level function items found"
    edits: list[tuple[int, int, str]] = []
    occupied = {n.text.decode() for n in _walk(root) if n.type == "identifier"}
    for function in functions:
        body = function.child_by_field_name("body")
        params = function.child_by_field_name("parameters")
        if body is None or params is None:
            continue
        if any(
            n.type in {"closure_expression", "macro_invocation", "function_item"}
            for n in _walk(body)
        ):
            continue
        for parameter in params.named_children:
            if parameter.type != "parameter":
                continue
            pattern = parameter.child_by_field_name("pattern")
            if pattern is None or pattern.type != "identifier":
                continue
            old = pattern.text.decode()
            if _has_shadowing_pattern(body, old):
                continue
            if any(
                n.type == "shorthand_field_initializer"
                and n.named_children
                and n.named_children[0].text.decode() == old
                for n in _walk(body)
            ):
                continue
            new = f"arg{rng.randrange(10000)}"
            while new in occupied:
                new = f"arg{rng.randrange(10000)}"
            occupied.add(new)
            edits.append((pattern.start_byte, pattern.end_byte, new))
            for reference in _walk(body):
                if reference.type != "identifier" or reference.text.decode() != old:
                    continue
                parent = reference.parent
                if (
                    parent
                    and parent.type == "field_expression"
                    and parent.child_by_field_name("field") == reference
                ):
                    continue
                edits.append((reference.start_byte, reference.end_byte, new))
    output = _edit(source, edits) if edits else source
    only_function_items = len(functions) == len(root.named_children)
    has_attributes = any(
        child.type == "attribute_item"
        for function in functions
        for child in function.named_children
    )
    if only_function_items and not has_attributes and len(functions) > 1:
        updated = parse_source("rust", output).root
        items = _functions(updated)
        chunks = [_text(output, item) for item in items]
        order = list(range(len(chunks)))
        rng.shuffle(order)
        if order == list(range(len(order))):
            order.reverse()
        output = _edit(
            output,
            [
                (
                    items[0].start_byte,
                    items[-1].end_byte,
                    "\n\n".join(chunks[i] for i in order),
                )
            ],
        )
    return (
        (output, None)
        if output != source
        else (source, "no safely renameable parameter or reorderable function found")
    )


def _has_shadowing_pattern(body: Node, name: str) -> bool:
    return any(
        n.type in {"let_declaration", "parameter"}
        and n.child_by_field_name("pattern") is not None
        and any(
            child.type == "identifier" and child.text.decode() == name
            for child in _walk(n.child_by_field_name("pattern"))
        )
        for n in _walk(body)
    )


def _inline_local(source: str, root: Node) -> tuple[str, str | None]:
    for function in _functions(root):
        body = function.child_by_field_name("body")
        if body is None:
            continue
        items = body.named_children
        for declaration, tail in pairwise(items):
            if declaration.type != "let_declaration" or tail.type != "identifier":
                continue
            pattern = declaration.child_by_field_name("pattern")
            value = declaration.child_by_field_name("value")
            if (
                pattern is None
                or pattern.type != "identifier"
                or value is None
                or tail.text != pattern.text
                or not _pure_expression(value)
            ):
                continue
            name = pattern.text
            references = [
                n for n in _walk(body) if n.type == "identifier" and n.text == name
            ]
            if len(references) != 2:
                continue
            replacement = _text(source, value)
            return _edit(
                source,
                [(declaration.start_byte, tail.end_byte, replacement)],
            ), None
    return source, "no pure single-use local directly returned from a function"


def _pure_expression(node: Node) -> bool:
    safe = {
        "identifier",
        "integer_literal",
        "float_literal",
        "boolean_literal",
        "string_literal",
        "raw_string_literal",
        "char_literal",
        "binary_expression",
        "unary_expression",
        "parenthesized_expression",
    }
    return node.type in safe and all(
        _pure_expression(child) for child in node.named_children
    )


def _add_dead_branches(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions:
        return source, "no top-level function item found"
    edits = []
    for function in functions:
        body = function.child_by_field_name("body")
        if body is None:
            continue
        count = rng.randint(1, 3)
        dead = "\n" + "\n".join("if false { let _ = (); }" for _ in range(count)) + "\n"
        edits.append((body.start_byte + 1, body.start_byte + 1, dead))
    if not edits:
        return source, "no function body found"
    return _edit(source, edits), None


def _loops_to_recursion(source: str, root: Node) -> tuple[str, str | None]:
    for function in _functions(root):
        body = function.child_by_field_name("body")
        if body is None:
            continue
        items = body.named_children
        if len(items) != 3:
            continue
        initialize, loop_statement, tail = items
        loop = next(
            (n for n in loop_statement.named_children if n.type == "for_expression"),
            None,
        )
        if (
            initialize.type != "let_declaration"
            or loop is None
            or tail.type != "identifier"
        ):
            continue
        accumulator = initialize.child_by_field_name("pattern")
        initial_value = initialize.child_by_field_name("value")
        loop_pattern = loop.child_by_field_name("pattern")
        iterator = loop.child_by_field_name("value")
        loop_body = loop.child_by_field_name("body")
        if (
            accumulator is None
            or accumulator.type != "identifier"
            or tail.text != accumulator.text
            or initial_value is None
            or initial_value.type != "integer_literal"
            or initial_value.text != b"0"
            or not any(n.type == "mutable_specifier" for n in _walk(initialize))
            or loop_pattern is None
            or loop_pattern.type != "identifier"
            or iterator is None
            or iterator.type != "identifier"
            or loop_body is None
        ):
            continue
        accumulator_name = accumulator.text.decode()
        item_name = loop_pattern.text.decode()
        iterator_name = iterator.text.decode()
        return_type = function.child_by_field_name("return_type")
        if return_type is None or return_type.text.decode() != "i32":
            continue
        if not _is_i32_slice_parameter(function, iterator_name):
            continue
        if not _safe_loop_body(loop_body, accumulator_name, item_name):
            continue
        helper = "mutation_visit"
        function_names = {
            n.text.decode() for n in _walk(root) if n.type == "identifier"
        }
        while helper in function_names:
            helper += "_"
        loop_contents = _text(source, loop_body)[1:-1]
        replacement = (
            f"fn {helper}(values: &[i32], index: usize, "
            f"mut {accumulator_name}: i32) -> i32 {{\n"
            f"    if index >= values.len() {{ return {accumulator_name}; }}\n"
            f"    let {item_name} = &values[index];\n"
            f"    {{{loop_contents}}}\n"
            f"    {helper}(values, index + 1, {accumulator_name})\n"
            f"}}\n"
            f"{helper}({iterator_name}, 0, 0)"
        )
        return _edit(
            source,
            [(initialize.start_byte, tail.end_byte, replacement)],
        ), None
    return source, "no safely convertible i32 slice accumulator loop found"


def _is_i32_slice_parameter(function: Node, name: str) -> bool:
    params = function.child_by_field_name("parameters")
    if params is None:
        return False
    for parameter in params.named_children:
        pattern = parameter.child_by_field_name("pattern")
        type_node = parameter.child_by_field_name("type")
        if (
            pattern is not None
            and pattern.type == "identifier"
            and pattern.text.decode() == name
            and type_node is not None
            and type_node.type == "reference_type"
            and "[i32]" in type_node.text.decode()
        ):
            return True
    return False


def _safe_loop_body(body: Node, accumulator: str, item: str) -> bool:
    if any(
        n.type
        in {
            "break_expression",
            "continue_expression",
            "return_expression",
            "try_expression",
            "closure_expression",
            "macro_invocation",
        }
        for n in _walk(body)
    ):
        return False
    if any(n.type == "let_declaration" for n in _walk(body)):
        return False
    allowed_names = {accumulator, item}
    if any(
        n.type == "identifier" and n.text.decode() not in allowed_names
        for n in _walk(body)
    ):
        return False
    assignments = [n for n in _walk(body) if n.type == "compound_assignment_expr"]
    if not assignments:
        return False
    for assignment in assignments:
        left = assignment.child_by_field_name("left")
        right = assignment.child_by_field_name("right")
        if (
            left is None
            or left.type != "identifier"
            or left.text.decode() != accumulator
            or right is None
            or not any(
                n.type == "identifier" and n.text.decode() == item for n in _walk(right)
            )
        ):
            return False
    return True
