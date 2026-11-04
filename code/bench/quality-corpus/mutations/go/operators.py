"""Conservative, syntax-checked Go held-out mutations.

``inline-all-locals`` inlines the first safe local of each function.
"""

from __future__ import annotations

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


def mutate(
    operator: str, source: str, pair_group_id: str, seed: int | None = None
) -> Mutation:
    if operator not in OPERATORS:
        raise ValueError(f"unknown Go mutation operator: {operator}")
    resolved_seed = stable_seed(operator, source, seed)
    rng = random_for(operator, source, resolved_seed)
    try:
        root = parse_source("go", source).root
    except (RuntimeError, OSError, ValueError) as exc:
        return _result(source, operator, pair_group_id, resolved_seed, str(exc))
    if root.has_error:
        raise ValueError("cannot mutate invalid Go source")
    if operator == "wrap-in-class":
        reason = "not applicable: Go has no class declarations"
        output = source
    elif operator == "reorder-and-rename":
        output, reason = _reorder_and_rename(source, root, rng)
    elif operator == "inline-all-locals":
        output, reason = _inline_locals(source, root)
    elif operator == "add-dead-branches":
        output, reason = _add_dead_branches(source, root, rng)
    else:
        output, reason = _loops_to_recursion(source, root)
    if reason is None and output == source:
        reason = "operator produced no source change"
    if reason is None:
        output = _format_go(output)
        if not _valid_go(output):
            raise ValueError(f"{operator} produced invalid Go source")
    return _result(
        source if reason else output, operator, pair_group_id, resolved_seed, reason
    )


def _result(
    source: str, operator: str, pair_group_id: str, seed: int, reason: str | None
) -> Mutation:
    return make_mutation(
        source, operator, OPERATORS[operator], pair_group_id, seed, reason
    )


def _parse(source: str):
    return parse_source("go", source)


def _format_go(source: str) -> str:
    if not shutil.which("gofmt"):
        return source
    with tempfile.TemporaryDirectory(prefix="varde-go-format-") as temp:
        path = Path(temp) / "candidate.go"
        path.write_text(source)
        result = subprocess.run(
            ["gofmt", "-e", "-w", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        return path.read_text() if result.returncode == 0 else source


def _valid_go(source: str) -> bool:
    try:
        if _parse(source).has_error():
            return False
    except RuntimeError, OSError, ValueError:
        return False
    if not shutil.which("go"):
        return True
    with tempfile.TemporaryDirectory(prefix="varde-go-syntax-") as temp:
        Path(temp, "go.mod").write_text("module corpus\n\ngo 1.20\n")
        path = Path(temp) / "candidate.go"
        path.write_text(source)
        fmt = subprocess.run(
            ["gofmt", "-e", "-d", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if fmt.returncode:
            return False
        vet = subprocess.run(
            ["go", "vet", str(path)],
            check=False,
            capture_output=True,
            text=True,
            cwd=temp,
        )
        return vet.returncode == 0


def _walk(node: Node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _text(source: str, node: Node) -> str:
    return source.encode()[node.start_byte : node.end_byte].decode()


def _edit(source: str, edits: list[tuple[int, int, str]]) -> str:
    data = source.encode()
    for start, end, value in sorted(edits, reverse=True):
        data = data[:start] + value.encode() + data[end:]
    return data.decode()


def _functions(root: Node) -> list[Node]:
    return [node for node in _walk(root) if node.type == "function_declaration"]


def _reorder_and_rename(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions:
        return source, "no function declarations found"
    edits: list[tuple[int, int, str]] = []
    identifiers = {
        node.text.decode() for node in _walk(root) if node.type == "identifier"
    }
    for fn in functions:
        params = fn.child_by_field_name("parameters")
        body = fn.child_by_field_name("body")
        if params is None or body is None:
            continue
        parameters = [
            n for n in params.named_children if n.type == "parameter_declaration"
        ]
        names = [p.child_by_field_name("name") for p in parameters]
        if any(n is None for n in names):
            continue
        for old_node in names:
            old = old_node.text.decode()
            # Conservative lexical safety: skip shadowed and captured parameter names.
            if any(
                n.type in {"short_var_declaration", "var_spec"}
                and n.child_by_field_name("left") is not None
                and any(
                    c.type == "identifier" and c.text.decode() == old
                    for c in _walk(n.child_by_field_name("left"))
                )
                for n in _walk(body)
            ):
                return source, f"parameter {old} may be shadowed"
            new = f"arg{rng.randrange(10000)}"
            while new in identifiers:
                new = f"arg{rng.randrange(10000)}"
            identifiers.add(new)
            edits.append((old_node.start_byte, old_node.end_byte, new))
            for ref in _walk(body):
                if ref.type == "identifier" and ref.text.decode() == old:
                    parent = ref.parent
                    if (
                        parent
                        and parent.type == "selector_expression"
                        and parent.child_by_field_name("field") == ref
                    ):
                        continue
                    if _is_keyed_element_key(ref):
                        continue
                    edits.append((ref.start_byte, ref.end_byte, new))
    output = _edit(source, edits) if edits else source
    # Reordering is safe only when all package declarations are functions with no init.
    top_functions = [n for n in root.named_children if n.type == "function_declaration"]
    has_only_package_and_functions = (
        len(top_functions) + 1 == len(root.named_children)
        and root.named_children[0].type == "package_clause"
    )
    if has_only_package_and_functions and len(top_functions) > 1:
        output_root = _parse(output).root
        output_functions = [
            n for n in output_root.named_children if n.type == "function_declaration"
        ]
        chunks = [_text(output, n) for n in output_functions]
        order = list(range(len(chunks)))
        rng.shuffle(order)
        if order == list(range(len(chunks))):
            order.reverse()
        start, end = output_functions[0].start_byte, output_functions[-1].end_byte
        output = _edit(output, [(start, end, "\n\n".join(chunks[i] for i in order))])
    return (
        (output, None)
        if output != source
        else (source, "no safely renameable parameters found")
    )


def _is_keyed_element_key(reference: Node) -> bool:
    """Return True when the identifier is a composite-literal field name."""
    ancestor = reference.parent
    while ancestor is not None and ancestor.type == "literal_element":
        ancestor = ancestor.parent
    if ancestor is None or ancestor.type != "keyed_element":
        return False
    key = ancestor.child_by_field_name("key")
    return key is not None and key.start_byte <= reference.start_byte < key.end_byte


def _inline_locals(source: str, root: Node) -> tuple[str, str | None]:
    edits: list[tuple[int, int, str]] = []
    for fn in _functions(root):
        body = fn.child_by_field_name("body")
        statements = (
            next((n for n in body.named_children if n.type == "statement_list"), None)
            if body
            else None
        )
        if statements is None:
            continue
        items = statements.named_children
        for first, second in pairwise(items):
            if (
                first.type != "short_var_declaration"
                or second.type != "return_statement"
            ):
                continue
            left = first.child_by_field_name("left")
            right = first.child_by_field_name("right")
            values = right.named_children if right else []
            names = left.named_children if left else []
            returned = second.named_children
            if len(names) != 1 or len(values) != 1 or len(returned) != 1:
                continue
            name, expr = names[0], values[0]
            if (
                name.type != "identifier"
                or returned[0].text != name.text
                or not _pure(expr)
            ):
                continue
            uses = [
                n for n in _walk(fn) if n.type == "identifier" and n.text == name.text
            ]
            if len(uses) != 2:
                continue
            expr_text = _text(source, expr)
            edits.append((first.start_byte, second.end_byte, f"return {expr_text}"))
            break
    if not edits:
        return source, "no safe pure single-use local immediately returned"
    return _edit(source, edits), None


def _pure(node: Node) -> bool:
    safe = {
        "identifier",
        "int_literal",
        "float_literal",
        "imaginary_literal",
        "rune_literal",
        "interpreted_string_literal",
        "raw_string_literal",
        "binary_expression",
        "unary_expression",
        "parenthesized_expression",
    }
    return node.type in safe and all(_pure(child) for child in node.named_children)


def _add_dead_branches(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    bodies = [
        n
        for n in _walk(root)
        if n.type == "block" and n.parent and n.parent.type == "function_declaration"
    ]
    if not bodies:
        return source, "no function body found"
    edits = []
    for body in bodies:
        count = rng.randint(1, 3)
        dead = "\n" + "\n".join("if false { _ = 0 }" for _ in range(count)) + "\n"
        edits.append((body.start_byte + 1, body.start_byte + 1, dead))
    return _edit(source, edits), None


def _loops_to_recursion(source: str, root: Node) -> tuple[str, str | None]:
    for loop in (n for n in _walk(root) if n.type == "for_statement"):
        clause = next(
            (n for n in loop.named_children if n.type == "range_clause"), None
        )
        body = loop.child_by_field_name("body")
        if clause is None or body is None:
            continue
        left = clause.child_by_field_name("left")
        right = clause.child_by_field_name("right")
        identifiers = left.named_children if left else []
        if len(identifiers) != 2 or right is None or right.type != "identifier":
            continue
        index_name, item_name = [n.text.decode() for n in identifiers]
        if index_name != "_":
            continue
        range_name = _text(source, right)
        statements = next(
            (n for n in body.named_children if n.type == "statement_list"), None
        )
        items = statements.named_children if statements else []
        if not items or any(
            n.type
            in {
                "break_statement",
                "continue_statement",
                "return_statement",
                "short_var_declaration",
                "defer_statement",
            }
            for n in _walk(body)
        ):
            continue
        updates = [n for n in _walk(body) if n.type == "assignment_statement"]
        unsafe_update = False
        for update in updates:
            left = update.child_by_field_name("left")
            right = update.child_by_field_name("right")
            left_values = left.named_children if left else []
            right_values = right.named_children if right else []
            if (
                len(left_values) != 1
                or len(right_values) != 1
                or len(update.children) < 2
                or update.children[1].type != "+="
                or right_values[0].type != "identifier"
                or right_values[0].text.decode() != item_name
            ):
                unsafe_update = True
                break
        if not updates or unsafe_update:
            continue
        if _loop_item_is_mutated(body, item_name):
            continue
        function = next(
            (
                n
                for n in _walk(root)
                if n.type == "function_declaration"
                and n.start_byte < loop.start_byte < n.end_byte
            ),
            None,
        )
        if function is None:
            continue
        if not _is_sequence_parameter(function, range_name):
            continue
        occupied = {n.text.decode() for n in _walk(function) if n.type == "identifier"}
        index = "mutationIndex"
        while index in occupied:
            index += "X"
        visitor = "mutationVisit"
        while visitor in occupied:
            visitor += "X"
        line_start = source.rfind("\n", 0, loop.start_byte) + 1
        indent = source[line_start : loop.start_byte]
        if indent.strip():
            indent = ""
        inner = indent + "\t"
        inner_body = source.encode()[body.start_byte + 1 : body.end_byte - 1].decode()
        item_edits = [
            (
                n.start_byte - body.start_byte - 1,
                n.end_byte - body.start_byte - 1,
                f"{range_name}[{index}]",
            )
            for n in _walk(body)
            if n.type == "identifier" and n.text.decode() == item_name
        ]
        for start, end, value in sorted(item_edits, reverse=True):
            inner_body = inner_body[:start] + value + inner_body[end:]
        replacement = (
            f"var {visitor} func(int)\n{indent}{visitor} = func({index} int) {{\n"
            f"{inner}if {index} >= len({range_name}) {{ return }}\n"
            f"{inner}{{{inner_body}{inner}}}\n"
            f"{inner}{visitor}({index} + 1)\n{indent}}}\n"
            f"{indent}{visitor}(0)"
        )
        return _edit(source, [(loop.start_byte, loop.end_byte, replacement)]), None
    return source, "no safely convertible slice range accumulator loop found"


def _loop_item_is_mutated(body: Node, item: str) -> bool:
    """Reject bodies that assign to, increment, or take the address of the
    loop value."""
    for node in _walk(body):
        if node.type in {"inc_statement", "dec_statement"} and any(
            child.type == "identifier" and child.text.decode() == item
            for child in node.named_children
        ):
            return True
        if node.type == "assignment_statement":
            left = node.child_by_field_name("left")
            if left is not None and any(
                child.type == "identifier" and child.text.decode() == item
                for child in _walk(left)
            ):
                return True
        if node.type == "unary_expression":
            operator = node.child_by_field_name("operator")
            operand = node.child_by_field_name("operand")
            if (
                operator is not None
                and operator.text == b"&"
                and operand is not None
                and operand.type == "identifier"
                and operand.text.decode() == item
            ):
                return True
    return False


def _is_sequence_parameter(function: Node, name: str) -> bool:
    """Require a slice or array parameter so indexing reads the ranged element."""
    params = function.child_by_field_name("parameters")
    if params is None:
        return False
    for parameter in params.named_children:
        if parameter.type != "parameter_declaration":
            continue
        parameter_name = parameter.child_by_field_name("name")
        parameter_type = parameter.child_by_field_name("type")
        if (
            parameter_name is not None
            and parameter_name.text.decode() == name
            and parameter_type is not None
            and parameter_type.type in {"slice_type", "array_type"}
        ):
            return True
    return False
