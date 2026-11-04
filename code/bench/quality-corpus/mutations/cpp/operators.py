"""Conservative, syntax-checked C++ held-out mutations.

Each operator returns a skip with a reason when the input shape cannot be
rewritten without changing behaviour. ``inline-all-locals`` inlines the first
safe local of each function; ``loops-to-recursion`` emits a recursive helper and
can exhaust the stack on very large inputs.
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


def cpp_grammar_available() -> bool:
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        root = Path(configured)
    else:
        root = (
            Path(
                os.environ.get(
                    "VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench"
                )
            )
            / "grammars"
        )
    return (
        next(root.glob("tree-sitter-language-pack/*/libs/libtree_sitter_cpp.*"), None)
        is not None
    )


def mutate(
    operator: str, source: str, pair_group_id: str, seed: int | None = None
) -> Mutation:
    if operator not in OPERATORS:
        raise ValueError(f"unknown C++ mutation operator: {operator}")
    resolved_seed = stable_seed(operator, source, seed)
    if not cpp_grammar_available():
        return _result(
            source,
            operator,
            pair_group_id,
            resolved_seed,
            "C++ tree-sitter grammar is not cached; skipped without downloading",
        )
    try:
        root = parse_source("cpp", source).root
    except (RuntimeError, OSError, ValueError) as exc:
        return _result(source, operator, pair_group_id, resolved_seed, str(exc))
    if root.has_error:
        raise ValueError("cannot mutate invalid C++ source")
    rng = random_for(operator, source, resolved_seed)
    if operator == "reorder-and-rename":
        output, reason = _reorder_and_rename(source, root, rng)
    elif operator == "inline-all-locals":
        output, reason = _inline_local(source, root)
    elif operator == "add-dead-branches":
        output, reason = _add_dead_branches(source, root, rng)
    elif operator == "wrap-in-class":
        output, reason = _wrap_in_class(source, root)
    else:
        output, reason = _loops_to_recursion(source, root)
    if reason is None and output == source:
        reason = "operator produced no source change"
    if reason is None and not _valid_cpp(output):
        raise ValueError(f"{operator} produced invalid C++ source")
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


def _function_name(function: Node) -> Node | None:
    declarator = function.child_by_field_name("declarator")
    while declarator is not None:
        if declarator.type == "function_declarator":
            name = declarator.child_by_field_name("declarator")
            return name if name and name.type == "identifier" else None
        nested = declarator.child_by_field_name("declarator")
        if nested is None:
            return None
        declarator = nested
    return None


def _functions(root: Node) -> list[Node]:
    return [node for node in root.named_children if node.type == "function_definition"]


_TOP_LEVEL_ORDER_INDEPENDENT = {
    "comment",
    "preproc_include",
    "preproc_def",
    "preproc_function_def",
    "preproc_ifdef",
    "preproc_if",
    "preproc_else",
    "preproc_call",
    "using_declaration",
    "namespace_definition",
    "type_definition",
    "alias_declaration",
    "declaration",
    "linkage_specification",
}

_CPP_FLOAT_TYPES = {"float", "double", "longdouble"}

_CPP_INTEGRAL_TYPES = {
    "char",
    "signedchar",
    "unsignedchar",
    "short",
    "shortint",
    "unsignedshort",
    "unsignedshortint",
    "int",
    "unsigned",
    "unsignedint",
    "long",
    "longint",
    "unsignedlong",
    "longlong",
    "longlongint",
    "unsignedlonglong",
    "bool",
    "size_t",
}

_CPP_UNSUPPORTED_SPECIFIERS = {
    "storage_class_specifier",
    "function_specifier",
    "type_qualifier",
    "attribute_specifier",
    "attribute_declaration",
    "ms_call_modifier",
    "ms_pointer_modifier",
}


def _normalized_type(node: Node) -> str:
    return re.sub(r"\s+", "", node.text.decode())


def _top_level_span_ok(root: Node, functions: list[Node]) -> bool:
    """Allow includes and order-independent declarations outside the function span."""
    children = root.named_children
    if not functions or len(functions) != sum(
        child.type == "function_definition" for child in children
    ):
        return False
    indices = [
        index
        for index, child in enumerate(children)
        if child.type == "function_definition"
    ]
    first, last = indices[0], indices[-1]
    for index, child in enumerate(children):
        if first <= index <= last:
            if child.type != "function_definition":
                return False
        elif child.type not in _TOP_LEVEL_ORDER_INDEPENDENT:
            return False
    return True


def _parameter_types(function: Node) -> dict[str, str]:
    declarator = function.child_by_field_name("declarator")
    params = (
        next(
            (node for node in _walk(declarator) if node.type == "parameter_list"), None
        )
        if declarator
        else None
    )
    types: dict[str, str] = {}
    if params is None:
        return types
    for parameter in params.named_children:
        if parameter.type != "parameter_declaration":
            continue
        type_node = parameter.child_by_field_name("type")
        name = _declared_identifier(parameter.child_by_field_name("declarator"))
        if type_node is not None and name is not None:
            types[name.text.decode()] = _normalized_type(type_node)
    return types


def _is_member_name(parent: Node, reference: Node) -> bool:
    """Return True only for the member-name side of ``a.b``, ``a->b``, or ``a::b``."""
    if parent.type == "field_expression":
        member = parent.child_by_field_name("field")
    elif parent.type == "qualified_identifier":
        member = parent.child_by_field_name("name")
    else:
        return False
    return member is not None and member.start_byte == reference.start_byte


def _value_matches_type(
    node: Node, declared: str, parameter_types: dict[str, str]
) -> bool:
    """Prove the expression's evident type equals the declared local type."""
    if node.type == "identifier":
        return parameter_types.get(node.text.decode()) == declared
    if node.type == "number_literal":
        text = node.text.decode()
        if any(character in text for character in ".eE"):
            return declared in _CPP_FLOAT_TYPES
        return declared in _CPP_INTEGRAL_TYPES or declared in _CPP_FLOAT_TYPES
    if node.type == "char_literal":
        return declared in {"char", "signedchar", "unsignedchar", "int"}
    if node.type in {"true", "false"}:
        return declared == "bool"
    if node.type == "string_literal":
        return declared in {"std::string", "string", "constchar*"}
    return all(
        _value_matches_type(child, declared, parameter_types)
        for child in node.named_children
    )


def _reorder_and_rename(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions:
        return source, "no top-level function definitions found"
    edits: list[tuple[int, int, str]] = []
    occupied = {node.text.decode() for node in _walk(root) if node.type == "identifier"}
    for function in functions:
        body = function.child_by_field_name("body")
        declarator = function.child_by_field_name("declarator")
        params = (
            next(
                (node for node in _walk(declarator) if node.type == "parameter_list"),
                None,
            )
            if declarator
            else None
        )
        if (
            body is None
            or params is None
            or any(
                node.type in {"lambda_expression", "function_definition"}
                for node in _walk(body)
            )
        ):
            continue
        for parameter in params.named_children:
            if parameter.type != "parameter_declaration":
                continue
            name = _declared_identifier(parameter.child_by_field_name("declarator"))
            if name is None or _has_shadowing_binding(body, name.text.decode()):
                continue
            old = name.text.decode()
            new = f"arg{rng.randrange(10000)}"
            while new in occupied:
                new = f"arg{rng.randrange(10000)}"
            occupied.add(new)
            edits.append((name.start_byte, name.end_byte, new))
            for reference in _walk(body):
                if reference.type != "identifier" or reference.text.decode() != old:
                    continue
                parent = reference.parent
                if parent is not None and _is_member_name(parent, reference):
                    continue
                edits.append((reference.start_byte, reference.end_byte, new))
    output = _edit(source, edits) if edits else source
    if len(functions) > 1 and _safe_to_reorder(root, functions):
        current = _functions(parse_source("cpp", output).root)
        chunks = [_text(output, function) for function in current]
        order = list(range(len(chunks)))
        rng.shuffle(order)
        if order == list(range(len(order))):
            order.reverse()
        output = _edit(
            output,
            [
                (
                    current[0].start_byte,
                    current[-1].end_byte,
                    "\n\n".join(chunks[i] for i in order),
                )
            ],
        )
    if output == source:
        return source, "no safely renameable parameters or reorderable functions found"
    return output, None


def _declared_identifier(node: Node | None) -> Node | None:
    if node is None:
        return None
    if node.type == "identifier":
        return node
    identifiers = [child for child in _walk(node) if child.type == "identifier"]
    return identifiers[-1] if identifiers else None


def _has_shadowing_binding(body: Node, name: str) -> bool:
    return any(
        node.type in {"declaration", "parameter_declaration"}
        and node != body
        and _declared_identifier(node.child_by_field_name("declarator")) is not None
        and _declared_identifier(node.child_by_field_name("declarator")).text.decode()
        == name
        for node in _walk(body)
    )


def _safe_to_reorder(root: Node, functions: list[Node]) -> bool:
    if not _top_level_span_ok(root, functions):
        return False
    names = {
        _function_name(function).text.decode()
        for function in functions
        if _function_name(function)
    }
    for function in functions:
        name = _function_name(function)
        body = function.child_by_field_name("body")
        if name is None or body is None:
            return False
        if any(
            node.type == "call_expression"
            and node.text.decode().split("(", 1)[0].strip() in names
            for node in _walk(body)
        ):
            return False
    return True


def _inline_local(source: str, root: Node) -> tuple[str, str | None]:
    edits: list[tuple[int, int, str]] = []
    for function in _functions(root):
        body = function.child_by_field_name("body")
        return_type = function.child_by_field_name("type")
        if body is None or return_type is None:
            continue
        parameter_types = _parameter_types(function)
        for declaration, returned in pairwise(body.named_children):
            if declaration.type != "declaration" or returned.type != "return_statement":
                continue
            declarators = [
                node
                for node in declaration.named_children
                if node.type == "init_declarator"
            ]
            if len(declarators) != 1:
                continue
            declarator = declarators[0]
            name = _declared_identifier(declarator.child_by_field_name("declarator"))
            value = declarator.child_by_field_name("value")
            declared_type = declaration.child_by_field_name("type")
            returns = returned.named_children
            if (
                name is None
                or value is None
                or declared_type is None
                or len(returns) != 1
                or returns[0].text != name.text
            ):
                continue
            if not _pure_expression(value):
                continue
            declared = _normalized_type(declared_type)
            if declared != _normalized_type(return_type):
                continue
            if not _value_matches_type(value, declared, parameter_types):
                continue
            refs = [
                node
                for node in _walk(body)
                if node.type == "identifier" and node.text == name.text
            ]
            if len(refs) != 2:
                continue
            edits.append(
                (
                    declaration.start_byte,
                    returned.end_byte,
                    f"return {_text(source, value)};",
                )
            )
            break
    if not edits:
        return (
            source,
            "no pure single-use local of a provable type immediately returned",
        )
    return _edit(source, edits), None


def _pure_expression(node: Node) -> bool:
    return node.type in {
        "identifier",
        "number_literal",
        "char_literal",
        "string_literal",
        "true",
        "false",
        "binary_expression",
        "unary_expression",
        "parenthesized_expression",
    } and all(_pure_expression(child) for child in node.named_children)


def _add_dead_branches(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    functions = _functions(root)
    edits = []
    for function in functions:
        body = function.child_by_field_name("body")
        if body is None:
            continue
        names = {
            node.text.decode() for node in _walk(body) if node.type == "identifier"
        }
        name = "mutationDead"
        while name in names:
            name += "X"
        branches = "\n".join(
            f"if (false) {{ int {name}{index} = 0; }}"
            for index in range(rng.randint(1, 3))
        )
        edits.append((body.start_byte + 1, body.start_byte + 1, "\n" + branches + "\n"))
    if not edits:
        return source, "no function bodies found"
    return _edit(source, edits), None


def _wrap_in_class(source: str, root: Node) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions or not _top_level_span_ok(root, functions):
        return source, "top-level declarations cannot be moved into a class safely"
    if any(
        child.type in _CPP_UNSUPPORTED_SPECIFIERS
        for function in functions
        for child in function.named_children
    ):
        return (
            source,
            (
                "functions with storage-class, inline, constexpr, or attribute "
                "specifiers cannot be moved without changing linkage"
            ),
        )
    names = [_function_name(function) for function in functions]
    if any(name is None for name in names) or len(
        {name.text.decode() for name in names if name}
    ) != len(names):
        return source, "overloaded or unsupported function declarators are skipped"
    class_name = "MutationContainer"
    while any(
        node.type == "identifier" and node.text.decode() == class_name
        for node in _walk(root)
    ):
        class_name += "X"
    methods = []
    wrappers = []
    for function, name_node in zip(functions, names, strict=True):
        assert name_node is not None  # noqa: S101 - Parsed function structure guarantees a name node.
        type_node = function.child_by_field_name("type")
        declarator = function.child_by_field_name("declarator")
        params = next(
            (node for node in _walk(declarator) if node.type == "parameter_list"), None
        )
        if (
            type_node is None
            or declarator is None
            or params is None
            or type_node.text == b"void"
        ):
            return source, "void or unsupported function signature is skipped"
        param_names = []
        for parameter in params.named_children:
            if parameter.type != "parameter_declaration":
                return source, "default or variadic parameters are skipped"
            param_name = _declared_identifier(
                parameter.child_by_field_name("declarator")
            )
            if param_name is None:
                return source, "unnamed function parameters are skipped"
            param_names.append(param_name.text.decode())
        function_text = _text(source, function)
        methods.append("static " + function_text)
        signature = _text(source, type_node) + " " + _text(source, declarator)
        args = ", ".join(param_names)
        wrappers.append(
            f"{signature} {{ return {class_name}::{name_node.text.decode()}({args}); }}"
        )
    replacement = (
        f"class {class_name} {{\npublic:\n"
        + "\n\n".join(methods)
        + "\n};\n\n"
        + "\n\n".join(wrappers)
    )
    return _edit(
        source, [(functions[0].start_byte, functions[-1].end_byte, replacement)]
    ), None


def _loops_to_recursion(source: str, root: Node) -> tuple[str, str | None]:
    for function in _functions(root):
        body = function.child_by_field_name("body")
        statements = body.named_children if body else []
        if len(statements) != 3:
            continue
        initialize, loop, returned = statements
        if (
            initialize.type != "declaration"
            or loop.type != "for_range_loop"
            or returned.type != "return_statement"
        ):
            continue
        init_declarators = [
            node for node in initialize.named_children if node.type == "init_declarator"
        ]
        if len(init_declarators) != 1 or len(returned.named_children) != 1:
            continue
        accumulator_node = _declared_identifier(
            init_declarators[0].child_by_field_name("declarator")
        )
        initial_value = init_declarators[0].child_by_field_name("value")
        if (
            accumulator_node is None
            or initial_value is None
            or initial_value.text != b"0"
            or returned.named_children[0].text != accumulator_node.text
        ):
            continue
        param_list = next(
            (
                node
                for node in _walk(function.child_by_field_name("declarator"))
                if node.type == "parameter_list"
            ),
            None,
        )
        parameter = (
            next(
                (
                    node
                    for node in param_list.named_children
                    if node.type == "parameter_declaration"
                ),
                None,
            )
            if param_list
            else None
        )
        param_name = (
            _declared_identifier(parameter.child_by_field_name("declarator"))
            if parameter
            else None
        )
        param_type = parameter.child_by_field_name("type") if parameter else None
        if (
            param_name is None
            or param_type is None
            or "std::vector<int>" not in _normalized_type(param_type)
        ):
            continue
        ranged = loop.child_by_field_name("right")
        if (
            ranged is None
            or ranged.type != "identifier"
            or ranged.text != param_name.text
        ):
            continue
        accumulator_type = initialize.child_by_field_name("type")
        if accumulator_type is None or _normalized_type(accumulator_type) != "int":
            continue
        item_type = loop.child_by_field_name("type")
        if item_type is None or _normalized_type(item_type) not in {"int", "auto"}:
            continue
        item = _declared_identifier(loop.child_by_field_name("declarator"))
        loop_body = loop.child_by_field_name("body")
        if (
            item is None
            or loop_body is None
            or not _safe_loop_body(
                loop_body,
                accumulator_node.text.decode(),
                item.text.decode(),
                param_name.text.decode(),
            )
        ):
            continue
        return_type = function.child_by_field_name("type")
        function_name = _function_name(function)
        if return_type is None or return_type.text != b"int" or function_name is None:
            continue
        occupied = {
            node.text.decode() for node in _walk(root) if node.type == "identifier"
        }
        helper = "mutationVisit"
        while helper in occupied:
            helper += "X"
        content = _text(source, loop_body)[1:-1]
        helper_text = (
            f"int {helper}(const std::vector<int>& {param_name.text.decode()}, "
            f"int mutationIndex, int {accumulator_node.text.decode()}) {{\n"
            "    if (mutationIndex >= static_cast<int>("
            f"{param_name.text.decode()}.size())) "
            f"return {accumulator_node.text.decode()};\n"
            f"    int {item.text.decode()} = "
            f"{param_name.text.decode()}[mutationIndex];\n"
            f"    {{{content}}}\n"
            f"    return {helper}({param_name.text.decode()}, mutationIndex + 1, "
            f"{accumulator_node.text.decode()});\n"
            "}\n\n"
        )
        prefix = (
            ""
            if re.search(r"#\s*include\s*[<\"]vector[>\"]", source)
            else "#include <vector>\n"
        )
        output = _edit(
            source,
            [
                (
                    initialize.start_byte,
                    returned.end_byte,
                    f"return {helper}({param_name.text.decode()}, 0, 0);",
                )
            ],
        )
        root_offset = function.start_byte
        output = _edit(output, [(root_offset, root_offset, prefix + helper_text)])
        return output, None
    return source, "no safely convertible vector accumulator range-loop found"


def _safe_loop_body(body: Node, accumulator: str, item: str, parameter: str) -> bool:
    if any(
        node.type
        in {
            "break_statement",
            "continue_statement",
            "return_statement",
            "lambda_expression",
            "call_expression",
            "declaration",
        }
        for node in _walk(body)
    ):
        return False
    allowed = {accumulator, item, parameter}
    if any(
        node.type == "identifier" and node.text.decode() not in allowed
        for node in _walk(body)
    ):
        return False
    assignments = [node for node in _walk(body) if node.type == "assignment_expression"]
    if not assignments:
        return False
    for assignment in assignments:
        left = assignment.child_by_field_name("left")
        operator = assignment.child_by_field_name("operator")
        right = assignment.child_by_field_name("right")
        if (
            left is None
            or left.type != "identifier"
            or left.text.decode() != accumulator
            or operator is None
            or operator.text != b"+="
            or right is None
            or item not in right.text.decode()
        ):
            return False
    return True


def _valid_cpp(source: str) -> bool:
    try:
        if parse_source("cpp", source).has_error():
            return False
    except RuntimeError, OSError, ValueError:
        return False
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        return True
    with tempfile.TemporaryDirectory(prefix="varde-cpp-syntax-") as temp:
        candidate = Path(temp) / "candidate.cpp"
        candidate.write_text(source)
        result = subprocess.run(  # noqa: S603,RUF100 - S603 is enabled in the task lint; arguments invoke the configured C++ compiler.
            [compiler, "-fsyntax-only", "-std=c++17", str(candidate)],
            check=False,
            capture_output=True,
            text=True,
        )
    return result.returncode == 0
