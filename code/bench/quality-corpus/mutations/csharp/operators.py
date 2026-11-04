"""Conservative, syntax-checked C# held-out mutations.

``inline-all-locals`` inlines the first safe local of each method. Dead branches
such as ``if (false) { int x = 0; }`` are unreachable but still compiled, so they
can raise unreachable-code warnings.
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


def csharp_grammar_available() -> bool:
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        root = Path(configured)
    else:
        cache_root = Path(
            os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
        )
        root = cache_root / "grammars"
    return (
        next(
            root.glob("tree-sitter-language-pack/*/libs/libtree_sitter_c_sharp.*"), None
        )
        is not None
        or next(
            root.glob("tree-sitter-language-pack/*/libs/libtree_sitter_csharp.*"), None
        )
        is not None
    )


def mutate(
    operator: str, source: str, pair_group_id: str, seed: int | None = None
) -> Mutation:
    if operator not in OPERATORS:
        raise ValueError(f"unknown C# mutation operator: {operator}")
    resolved_seed = stable_seed(operator, source, seed)
    rng = random_for(operator, source, resolved_seed)
    if not csharp_grammar_available():
        return _result(
            source,
            operator,
            pair_group_id,
            resolved_seed,
            "C# tree-sitter grammar is not cached; skipped without downloading",
        )
    try:
        root = parse_source("csharp", source).root
    except (RuntimeError, OSError, ValueError) as exc:
        return _result(source, operator, pair_group_id, resolved_seed, str(exc))
    if root.has_error:
        raise ValueError("cannot mutate invalid C# source")
    if operator == "wrap-in-class":
        output, reason = (
            source,
            "not applicable: C# functions are already class methods",
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
    if reason is None and not _valid_csharp(output):
        if not _valid_csharp(source):
            reason = "input does not compile"
        else:
            raise ValueError(f"{operator} produced invalid C# source")
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
    output = _rename_private_parameters(source, root, methods, rng)
    for declaration in (n for n in _walk(root) if n.type == "class_declaration"):
        body = declaration.child_by_field_name("body")
        if body is None:
            continue
        members = body.named_children
        if len(members) != len(methods) or any(
            n.type != "method_declaration" for n in members
        ):
            continue
        output = _reorder_class_methods(output, body, rng)
        break
    return (
        (output, None)
        if output != source
        else (source, "no safely renameable parameters or reorderable methods found")
    )


def _rename_private_parameters(
    source: str, root: Node, methods: list[Node], rng: random.Random
) -> str:
    edits: list[tuple[int, int, str]] = []
    occupied = {n.text.decode() for n in _walk(root) if n.type == "identifier"}
    has_named_arguments = any(
        node.type == "argument" and node.child_by_field_name("name") is not None
        for node in _walk(root)
    )
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
        modifiers = {
            child.text.decode()
            for child in method.named_children
            if child.type == "modifier"
        }
        if (
            modifiers.intersection({"public", "protected", "internal"})
            or has_named_arguments
        ):
            continue
        for parameter in params.named_children:
            if parameter.type != "parameter":
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
                    and parent.type == "member_access_expression"
                    and parent.child_by_field_name("name") == reference
                ):
                    continue
                edits.append((reference.start_byte, reference.end_byte, new))
    return _edit(source, edits) if edits else source


def _reorder_class_methods(source: str, body: Node, rng: random.Random) -> str:
    output_root = parse_source("csharp", source).root
    updated_body = next(
        (
            node.child_by_field_name("body")
            for node in _walk(output_root)
            if node.type == "class_declaration"
            and node.child_by_field_name("body") is not None
            and node.child_by_field_name("body").start_byte == body.start_byte
        ),
        None,
    )
    if updated_body is None:
        return source
    current_methods = updated_body.named_children
    chunks = [_text(source, method) for method in current_methods]
    order = list(range(len(chunks)))
    rng.shuffle(order)
    if order == list(range(len(order))):
        order.reverse()
    if len(chunks) < 2:
        return source
    return _edit(
        source,
        [
            (
                current_methods[0].start_byte,
                current_methods[-1].end_byte,
                "\n\n".join(chunks[index] for index in order),
            )
        ],
    )


def _has_shadowing_binding(body: Node, name: str) -> bool:
    return any(
        node.type in {"variable_declarator", "parameter"}
        and node.child_by_field_name("name") is not None
        and node.child_by_field_name("name").text.decode() == name
        for node in _walk(body)
    )


def _inline_local(source: str, root: Node) -> tuple[str, str | None]:
    edits: list[tuple[int, int, str]] = []
    for method in _methods(root):
        body = method.child_by_field_name("body")
        return_type = method.child_by_field_name("returns")
        if body is None or return_type is None:
            continue
        parameter_types = _parameter_types(method)
        for declaration, returned in pairwise(body.named_children):
            if (
                declaration.type != "local_declaration_statement"
                or returned.type != "return_statement"
            ):
                continue
            variable = next(
                (
                    node
                    for node in _walk(declaration)
                    if node.type == "variable_declarator"
                ),
                None,
            )
            value = _variable_value(variable) if variable else None
            name = variable.child_by_field_name("name") if variable else None
            local_type = next(
                (
                    node.child_by_field_name("type")
                    for node in declaration.named_children
                    if node.type == "variable_declaration"
                ),
                None,
            )
            return_values = returned.named_children
            if (
                name is None
                or value is None
                or local_type is None
                or len(return_values) != 1
            ):
                continue
            if name.type != "identifier" or return_values[0].text != name.text:
                continue
            if not _pure_expression(value):
                continue
            declared = _normalized_type(local_type)
            if declared != _normalized_type(return_type):
                continue
            if not _value_matches_type(value, declared, parameter_types):
                continue
            references = [
                node
                for node in _walk(body)
                if node.type == "identifier" and node.text == name.text
            ]
            if len(references) != 2:
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


_CSHARP_FLOAT_TYPES = {"float", "double", "decimal"}

_CSHARP_INTEGRAL_TYPES = {
    "byte",
    "sbyte",
    "short",
    "ushort",
    "int",
    "uint",
    "long",
    "ulong",
    "char",
}


def _normalized_type(node: Node) -> str:
    return re.sub(r"\s+", "", node.text.decode())


def _parameter_types(method: Node) -> dict[str, str]:
    params = method.child_by_field_name("parameters")
    types: dict[str, str] = {}
    if params is None:
        return types
    for parameter in params.named_children:
        if parameter.type != "parameter":
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
    if node.type == "integer_literal":
        return declared in _CSHARP_INTEGRAL_TYPES or declared in _CSHARP_FLOAT_TYPES
    if node.type == "real_literal":
        return declared in _CSHARP_FLOAT_TYPES
    if node.type == "boolean_literal":
        return declared == "bool"
    if node.type == "character_literal":
        return declared in {"char", "int"}
    if node.type == "string_literal":
        return declared == "string"
    return all(
        _value_matches_type(child, declared, parameter_types)
        for child in node.named_children
    )


def _pure_expression(node: Node) -> bool:
    safe = {
        "identifier",
        "integer_literal",
        "real_literal",
        "boolean_literal",
        "character_literal",
        "string_literal",
        "binary_expression",
        "prefix_unary_expression",
        "parenthesized_expression",
    }
    return node.type in safe and all(
        _pure_expression(child) for child in node.named_children
    )


def _variable_value(variable: Node) -> Node | None:
    name = variable.child_by_field_name("name")
    return next((child for child in variable.named_children if child != name), None)


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
        names = {
            node.text.decode() for node in _walk(body) if node.type == "identifier"
        }
        dead_name = "mutationDead"
        while dead_name in names:
            dead_name += "X"
        count = rng.randint(1, 3)
        branches = "\n".join(
            f"if (false) {{ int {dead_name}{index} = 0; }}" for index in range(count)
        )
        edits.append((body.start_byte + 1, body.start_byte + 1, "\n" + branches + "\n"))
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
            initialize.type != "local_declaration_statement"
            or loop.type != "for_statement"
            or returned.type != "return_statement"
        ):
            continue
        declarations = [
            node for node in _walk(initialize) if node.type == "variable_declarator"
        ]
        return_values = returned.named_children
        if len(declarations) != 1 or len(return_values) != 1:
            continue
        accumulator = declarations[0].child_by_field_name("name")
        initial_value = _variable_value(declarations[0])
        declaration = next(
            (
                node
                for node in initialize.named_children
                if node.type == "variable_declaration"
            ),
            None,
        )
        local_type = declaration.child_by_field_name("type") if declaration else None
        if (
            accumulator is None
            or accumulator.type != "identifier"
            or initial_value is None
            or initial_value.text != b"0"
            or return_values[0].text != accumulator.text
            or local_type is None
            or local_type.text.decode() != "int"
        ):
            continue
        array_name = _array_parameter_name(method)
        index = _for_index(loop, array_name)
        loop_body = loop.child_by_field_name("body")
        if array_name is None or index is None or loop_body is None:
            continue
        accumulator_name = accumulator.text.decode()
        if not _safe_loop_body(loop_body, accumulator_name, array_name, index):
            continue
        class_body = _ancestor(method, "declaration_list")
        if class_body is None:
            continue
        helper = "mutationVisit"
        occupied = {
            node.text.decode() for node in _walk(root) if node.type == "identifier"
        }
        while helper in occupied:
            helper += "X"
        content = _text(source, loop_body)[1:-1]
        helper_method = (
            f"\n    private static int {helper}(int[] {array_name}, int {index}, "
            f"int {accumulator_name}) {{\n"
            f"        if ({index} >= {array_name}.Length) return {accumulator_name};\n"
            f"        {{{content}}}\n"
            f"        return {helper}({array_name}, {index} + 1, {accumulator_name});\n"
            "    }\n"
        )
        return _edit(
            source,
            [
                (
                    initialize.start_byte,
                    returned.end_byte,
                    f"return {helper}({array_name}, 0, 0);",
                ),
                (class_body.end_byte - 1, class_body.end_byte - 1, helper_method),
            ],
        ), None
    return source, "no safely convertible int-array accumulator loop found"


def _for_index(loop: Node, array_name: str | None) -> str | None:
    init = next(
        (node for node in loop.named_children if node.type == "variable_declaration"),
        None,
    )
    condition = loop.child_by_field_name("condition")
    update = loop.child_by_field_name("update")
    if init is None or condition is None or update is None or array_name is None:
        return None
    declarators = [node for node in _walk(init) if node.type == "variable_declarator"]
    if len(declarators) != 1:
        return None
    name = declarators[0].child_by_field_name("name")
    value = _variable_value(declarators[0])
    local_type = init.child_by_field_name("type")
    if (
        name is None
        or value is None
        or value.text != b"0"
        or local_type is None
        or local_type.text.decode() != "int"
    ):
        return None
    index = name.text.decode()
    condition_text = re.sub(r"\s+", "", condition.text.decode())
    if (
        condition_text != f"{index}<{array_name}.Length"
        or update.text.decode() != f"{index}++"
    ):
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
        node.type
        in {
            "break_statement",
            "continue_statement",
            "return_statement",
            "lambda_expression",
            "invocation_expression",
            "local_declaration_statement",
        }
        for node in _walk(body)
    ):
        return False
    allowed = {accumulator, array_name, index, "Length"}
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


def _dotnet_sdk_available() -> bool:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        return False
    result = subprocess.run(
        [dotnet, "--list-sdks"], check=False, capture_output=True, text=True
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _valid_csharp(source: str) -> bool:
    try:
        if parse_source("csharp", source).has_error():
            return False
    except RuntimeError:
        return False
    except OSError:
        return False
    except ValueError:
        return False
    if not _dotnet_sdk_available():
        return True
    dotnet = shutil.which("dotnet")
    assert dotnet is not None  # noqa: S101 - The preceding SDK lookup handles a missing executable.
    sdk_list = subprocess.run(
        [dotnet, "--list-sdks"], check=False, capture_output=True, text=True
    )
    versions = re.findall(r"^(\d+)\.[\d.]+\s", sdk_list.stdout, re.MULTILINE)
    target = max(map(int, versions)) if versions else 8
    with tempfile.TemporaryDirectory(prefix="varde-csharp-syntax-") as temp:
        root = Path(temp)
        (root / "Candidate.cs").write_text(source)
        project = root / "Candidate.csproj"
        project.write_text(
            f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>'
            f"net{target}.0</TargetFramework><EnableDefaultCompileItems>true"
            "</EnableDefaultCompileItems></PropertyGroup></Project>"
        )
        config = root / "NuGet.Config"
        config.write_text(
            "<configuration><packageSources><clear /></packageSources></configuration>"
        )
        restore = subprocess.run(
            [dotnet, "restore", str(project), "--configfile", str(config), "--nologo"],
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
        )
        if restore.returncode:
            return False
        build = subprocess.run(
            [
                dotnet,
                "build",
                str(project),
                "--no-restore",
                "--nologo",
                "--verbosity",
                "quiet",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
        )
        return build.returncode == 0
