"""Conservative, syntax-checked Java held-out mutations.

``inline-all-locals`` inlines the first safe local of each method.
"""

from __future__ import annotations

import os
import random
import re
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


def java_grammar_available() -> bool:
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        root = Path(configured)
    else:
        cache_root = Path(
            os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
        )
        root = cache_root / "grammars"
    return (
        next(root.glob("tree-sitter-language-pack/*/libs/libtree_sitter_java.*"), None)
        is not None
    )


def mutate(
    operator: str, source: str, pair_group_id: str, seed: int | None = None
) -> Mutation:
    if operator not in OPERATORS:
        raise ValueError(f"unknown Java mutation operator: {operator}")
    resolved_seed = stable_seed(operator, source, seed)
    rng = random_for(operator, source, resolved_seed)
    if not java_grammar_available():
        return _result(
            source,
            operator,
            pair_group_id,
            resolved_seed,
            "Java tree-sitter grammar is not cached; skipped without downloading",
        )
    try:
        root = parse_source("java", source).root
    except (RuntimeError, OSError, ValueError) as exc:
        return _result(source, operator, pair_group_id, resolved_seed, str(exc))
    if root.has_error:
        raise ValueError("cannot mutate invalid Java source")
    if operator == "wrap-in-class":
        output, reason = (
            source,
            (
                "not applicable: Java methods are already class members; a "
                "delegating class would duplicate every method and change dispatch"
            ),
        )
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
    if reason is None and not _valid_java(output):
        raise ValueError(f"{operator} produced invalid Java source")
    return _result(
        source if reason else output, operator, pair_group_id, resolved_seed, reason
    )


def _result(
    source: str, operator: str, pair_group_id: str, seed: int, reason: str | None
) -> Mutation:
    return make_mutation(
        source, operator, OPERATORS[operator], pair_group_id, seed, reason
    )


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


def _methods(root: Node) -> list[Node]:
    return [node for node in _walk(root) if node.type == "method_declaration"]


def _reorder_and_rename(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    methods = _methods(root)
    if not methods:
        return source, "no method declarations found"
    edits: list[tuple[int, int, str]] = []
    occupied = {n.text.decode() for n in _walk(root) if n.type == "identifier"}
    for method in methods:
        body = method.child_by_field_name("body")
        params = method.child_by_field_name("parameters")
        if body is None or params is None:
            continue
        if any(
            n.type in {"lambda_expression", "class_declaration", "method_declaration"}
            for n in _walk(body)
        ):
            continue
        for parameter in params.named_children:
            if parameter.type != "formal_parameter":
                continue
            name = parameter.child_by_field_name("name")
            if name is None:
                continue
            old = name.text.decode()
            if _has_shadowing_binding(body, old):
                continue
            new = f"arg{rng.randrange(10000)}"
            while new in occupied:
                new = f"arg{rng.randrange(10000)}"
            occupied.add(new)
            edits.append((name.start_byte, name.end_byte, new))
            for reference in _walk(body):
                if reference.type != "identifier" or reference.text.decode() != old:
                    continue
                parent = reference.parent
                if (
                    parent
                    and parent.type == "field_access"
                    and parent.named_children[-1] == reference
                ):
                    continue
                if (
                    parent
                    and parent.type == "method_invocation"
                    and parent.child_by_field_name("name") == reference
                ):
                    continue
                edits.append((reference.start_byte, reference.end_byte, new))
    output = _edit(source, edits) if edits else source
    for class_body in (n for n in _walk(root) if n.type == "class_body"):
        members = class_body.named_children
        if len(members) != len(methods) or any(
            n.type != "method_declaration" for n in members
        ):
            continue
        current = parse_source("java", output).root
        bodies = [n for n in _walk(current) if n.type == "class_body"]
        updated = next(
            (n for n in bodies if n.start_byte == class_body.start_byte), None
        )
        if updated is None:
            continue
        current_methods = updated.named_children
        chunks = [_text(output, method) for method in current_methods]
        order = list(range(len(chunks)))
        rng.shuffle(order)
        if order == list(range(len(order))):
            order.reverse()
        if len(chunks) > 1:
            output = _edit(
                output,
                [
                    (
                        current_methods[0].start_byte,
                        current_methods[-1].end_byte,
                        "\n\n".join(chunks[i] for i in order),
                    )
                ],
            )
        break
    return (
        (output, None)
        if output != source
        else (source, "no safely renameable parameters or reorderable methods found")
    )


def _has_shadowing_binding(body: Node, name: str) -> bool:
    return any(
        n.type in {"variable_declarator", "formal_parameter", "catch_formal_parameter"}
        and n.child_by_field_name("name") is not None
        and n.child_by_field_name("name").text.decode() == name
        for n in _walk(body)
    )


def _inline_local(source: str, root: Node) -> tuple[str, str | None]:
    edits: list[tuple[int, int, str]] = []
    for method in _methods(root):
        body = method.child_by_field_name("body")
        return_type = method.child_by_field_name("type")
        if body is None or return_type is None:
            continue
        parameter_types = _parameter_types(method)
        for declaration, returned in pairwise(body.named_children):
            if (
                declaration.type != "local_variable_declaration"
                or returned.type != "return_statement"
            ):
                continue
            declarators = [
                n for n in declaration.named_children if n.type == "variable_declarator"
            ]
            values = returned.named_children
            if len(declarators) != 1 or len(values) != 1:
                continue
            name = declarators[0].child_by_field_name("name")
            value = declarators[0].child_by_field_name("value")
            declared_type = declaration.child_by_field_name("type")
            if (
                name is None
                or name.type != "identifier"
                or value is None
                or declared_type is None
                or values[0].text != name.text
            ):
                continue
            if not _pure_expression(value):
                continue
            declared = _normalized_type(declared_type)
            if declared != _normalized_type(return_type):
                continue
            if not _value_matches_type(value, declared, parameter_types):
                continue
            references = [
                n for n in _walk(body) if n.type == "identifier" and n.text == name.text
            ]
            if len(references) != 2:
                continue
            expression = _text(source, value)
            edits.append(
                (declaration.start_byte, returned.end_byte, f"return {expression};")
            )
            break
    if not edits:
        return (
            source,
            "no pure single-use local of a provable type immediately returned",
        )
    return _edit(source, edits), None


_JAVA_FLOAT_TYPES = {"float", "double"}

_JAVA_INTEGRAL_TYPES = {"byte", "short", "int", "long", "char"}


def _normalized_type(node: Node) -> str:
    return re.sub(r"\s+", "", node.text.decode())


def _parameter_types(method: Node) -> dict[str, str]:
    params = method.child_by_field_name("parameters")
    types: dict[str, str] = {}
    if params is None:
        return types
    for parameter in params.named_children:
        if parameter.type != "formal_parameter":
            continue
        name = parameter.child_by_field_name("name")
        type_node = parameter.child_by_field_name("type")
        if name is not None and type_node is not None:
            types[name.text.decode()] = _normalized_type(type_node)
    return types


def _value_matches_type(
    node: Node, declared: str, parameter_types: dict[str, str]
) -> bool:
    """Prove the expression's evident type equals the declared local type."""
    if node.type == "identifier":
        return parameter_types.get(node.text.decode()) == declared
    if node.type in {
        "decimal_integer_literal",
        "hex_integer_literal",
        "octal_integer_literal",
        "binary_integer_literal",
    }:
        return declared in _JAVA_INTEGRAL_TYPES or declared in _JAVA_FLOAT_TYPES
    if node.type == "decimal_floating_point_literal":
        return declared in _JAVA_FLOAT_TYPES
    if node.type in {"true", "false"}:
        return declared == "boolean"
    if node.type == "character_literal":
        return declared in {"char", "int", "long"}
    if node.type == "string_literal":
        return declared in {"String", "java.lang.String"}
    return all(
        _value_matches_type(child, declared, parameter_types)
        for child in node.named_children
    )


def _pure_expression(node: Node) -> bool:
    safe = {
        "identifier",
        "decimal_integer_literal",
        "hex_integer_literal",
        "octal_integer_literal",
        "binary_integer_literal",
        "decimal_floating_point_literal",
        "true",
        "false",
        "character_literal",
        "string_literal",
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
    methods = _methods(root)
    if not methods:
        return source, "no method declarations found"
    edits = []
    for method in methods:
        body = method.child_by_field_name("body")
        if body is None:
            continue
        names = {n.text.decode() for n in _walk(body) if n.type == "identifier"}
        dead_name = "mutationDead"
        while dead_name in names:
            dead_name += "X"
        count = rng.randint(1, 3)
        branch = "\n".join(
            f"if (false) {{ int {dead_name}{index} = 0; }}" for index in range(count)
        )
        edits.append((body.start_byte + 1, body.start_byte + 1, "\n" + branch + "\n"))
    if not edits:
        return source, "no method bodies found"
    return _edit(source, edits), None


def _loops_to_recursion(source: str, root: Node) -> tuple[str, str | None]:
    for method in _methods(root):
        body = method.child_by_field_name("body")
        if body is None or len(body.named_children) != 3:
            continue
        initialize, loop, returned = body.named_children
        if (
            initialize.type != "local_variable_declaration"
            or loop.type != "for_statement"
            or returned.type != "return_statement"
        ):
            continue
        declarators = [
            n for n in initialize.named_children if n.type == "variable_declarator"
        ]
        return_values = returned.named_children
        if len(declarators) != 1 or len(return_values) != 1:
            continue
        accumulator = declarators[0].child_by_field_name("name")
        initial = declarators[0].child_by_field_name("value")
        if (
            accumulator is None
            or initial is None
            or initial.text != b"0"
            or return_values[0].text != accumulator.text
        ):
            continue
        declared_type = initialize.child_by_field_name("type")
        if declared_type is None or declared_type.text.decode() != "int":
            continue
        array_name = _array_parameter_name(method)
        iterator = _for_index(loop, array_name)
        loop_body = loop.child_by_field_name("body")
        if array_name is None or iterator is None or loop_body is None:
            continue
        accumulator_name = accumulator.text.decode()
        if not _safe_loop_body(loop_body, accumulator_name, array_name, iterator):
            continue
        class_body = _ancestor(method, "class_body")
        if class_body is None:
            continue
        helper = "mutationVisit"
        occupied = {n.text.decode() for n in _walk(root) if n.type == "identifier"}
        while helper in occupied:
            helper += "X"
        loop_content = _text(source, loop_body)[1:-1]
        replacement = f"return {helper}({array_name}, 0, 0);"
        helper_method = (
            f"\n    private static int {helper}(int[] {array_name}, int {iterator}, "
            f"int {accumulator_name}) {{\n"
            f"        if ({iterator} >= {array_name}.length) "
            f"return {accumulator_name};\n"
            f"        {{{loop_content}}}\n"
            f"        return {helper}({array_name}, {iterator} + 1, "
            f"{accumulator_name});\n"
            "    }\n"
        )
        return _edit(
            source,
            [
                (initialize.start_byte, returned.end_byte, replacement),
                (class_body.end_byte - 1, class_body.end_byte - 1, helper_method),
            ],
        ), None
    return source, "no safely convertible int-array accumulator loop found"


def _for_index(loop: Node, array_name: str | None) -> str | None:
    init = loop.child_by_field_name("init")
    condition = loop.child_by_field_name("condition")
    update = loop.child_by_field_name("update")
    if init is None or condition is None or update is None or array_name is None:
        return None
    declarators = [n for n in _walk(init) if n.type == "variable_declarator"]
    if len(declarators) != 1:
        return None
    name = declarators[0].child_by_field_name("name")
    value = declarators[0].child_by_field_name("value")
    if name is None or value is None or value.text != b"0":
        return None
    index = name.text.decode()
    normalized_condition = re.sub(r"\s+", "", condition.text.decode())
    normalized_update = re.sub(r"\s+", "", update.text.decode())
    if normalized_condition != f"{index}<{array_name}.length":
        return None
    if normalized_update != f"{index}++":
        return None
    return index


def _array_parameter_name(method: Node) -> str | None:
    params = method.child_by_field_name("parameters")
    if params is None:
        return None
    for parameter in params.named_children:
        name = parameter.child_by_field_name("name")
        type_node = parameter.child_by_field_name("type")
        if (
            name is not None
            and type_node is not None
            and type_node.type == "array_type"
            and type_node.text.decode() == "int[]"
        ):
            return name.text.decode()
    return None


def _safe_loop_body(body: Node, accumulator: str, array_name: str, index: str) -> bool:
    if any(
        n.type
        in {
            "break_statement",
            "continue_statement",
            "return_statement",
            "lambda_expression",
            "method_invocation",
            "local_variable_declaration",
        }
        for n in _walk(body)
    ):
        return False
    allowed = {accumulator, array_name, index, "length"}
    if any(
        n.type == "identifier" and n.text.decode() not in allowed for n in _walk(body)
    ):
        return False
    assignments = [n for n in _walk(body) if n.type == "assignment_expression"]
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
            or array_name not in right.text.decode()
            or index not in right.text.decode()
            or not any(child.type == "+=" for child in assignment.children)
        ):
            return False
    return True


def _ancestor(node: Node, node_type: str) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type == node_type:
            return parent
        parent = parent.parent
    return None


def _valid_java(source: str) -> bool:
    try:
        if parse_source("java", source).has_error():
            return False
    except RuntimeError, OSError, ValueError:
        return False
    javac = shutil.which("javac")
    if javac is None:
        return True
    root = parse_source("java", source).root
    top_class = next(
        (n for n in root.named_children if n.type == "class_declaration"), None
    )
    if top_class is None or top_class.child_by_field_name("name") is None:
        return False
    filename = top_class.child_by_field_name("name").text.decode() + ".java"
    with tempfile.TemporaryDirectory(prefix="varde-java-syntax-") as temp:
        path = Path(temp) / filename
        path.write_text(source)
        result = subprocess.run(  # noqa: S603 - Runs the configured Java compiler on generated source.
            [javac, "-proc:none", "-d", temp, str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
