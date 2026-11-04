"""Tree-sitter based TypeScript held-out mutations."""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import pairwise

from tree_sitter import Node

from ..core import (
    Mutation,
    make_mutation,
    parse_typescript,
    random_for,
    stable_seed,
    typescript_grammar_available,
)

OPERATORS = {
    "reorder-and-rename": "invariant",
    "inline-all-locals": "invariant",
    "add-dead-branches": "invariant",
    "wrap-in-class": "increased structural debt",
    "loops-to-recursion": "increased structural debt",
}


@dataclass(frozen=True)
class FunctionRecord:
    node: Node
    declaration: Node
    exported: bool


@dataclass(frozen=True)
class LoopPlan:
    loop: Node
    iterable: str
    accumulator: str


def mutate(
    operator: str, source: str, pair_group_id: str, seed: int | None = None
) -> Mutation:
    if operator not in OPERATORS:
        raise ValueError(f"unknown TypeScript mutation operator: {operator}")
    if not typescript_grammar_available():
        return _result(
            source,
            operator,
            pair_group_id,
            seed,
            "TypeScript grammar is not cached; skipped without downloading",
        )
    parsed = parse_typescript(source)
    if parsed.has_error():
        raise ValueError("cannot mutate invalid TypeScript source")
    resolved_seed = stable_seed(operator, source, seed)
    rng = random_for(operator, source, resolved_seed)
    skip_reason: str | None = None
    if operator == "reorder-and-rename":
        output, skip_reason = _reorder_and_rename(source, parsed.root, rng)
    elif operator == "inline-all-locals":
        output, skip_reason = _inline_locals(source, parsed.root)
    elif operator == "add-dead-branches":
        output = _add_dead_branches(source, parsed.root, rng)
    elif operator == "wrap-in-class":
        output, skip_reason = _wrap_in_class(source, parsed.root)
    else:
        output, skip_reason = _loops_to_recursion(source, parsed.root)
    if skip_reason is None and output == source:
        skip_reason = "operator produced no source change"
    if skip_reason is None and not _valid_typescript(output):
        raise ValueError(f"{operator} produced invalid TypeScript")
    return _result(
        source if skip_reason else output,
        operator,
        pair_group_id,
        resolved_seed,
        skip_reason,
    )


def _result(
    source: str,
    operator: str,
    pair_group_id: str,
    seed: int | None,
    skip_reason: str | None,
) -> Mutation:
    return make_mutation(
        source,
        operator,
        OPERATORS[operator],
        pair_group_id,
        seed,
        skip_reason,
    )


def _valid_typescript(source: str) -> bool:
    try:
        return not parse_typescript(source).has_error()
    except RuntimeError, OSError, ValueError:
        return False


def _walk(node: Node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _functions(root: Node) -> list[FunctionRecord]:
    records = []
    for child in root.named_children:
        if child.type == "function_declaration":
            records.append(FunctionRecord(child, child, False))
        elif child.type == "export_statement":
            declaration = child.child_by_field_name("declaration")
            if declaration and declaration.type == "function_declaration":
                records.append(FunctionRecord(child, declaration, True))
    return records


def _reorder_and_rename(
    source: str, root: Node, rng: random.Random
) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions:
        return source, "no top-level function declarations found"
    if len(functions) > 1 and _safe_to_reorder(root, functions):
        chunks = [
            _source_slice(source, function.node.start_byte, function.node.end_byte)
            for function in functions
        ]
        original = list(chunks)
        rng.shuffle(chunks)
        if chunks == original:
            chunks.reverse()
        start, end = functions[0].node.start_byte, functions[-1].node.end_byte
        source = _apply_edits(source, [(start, end, "\n\n".join(chunks))])
        root = parse_typescript(source).root
        functions = _functions(root)
    edits: list[tuple[int, int, str]] = []
    occupied = {node.text.decode() for node in _walk(root) if node.type == "identifier"}
    for record in functions:
        function = record.declaration
        if any(
            node.type
            in {"function_declaration", "arrow_function", "function_expression"}
            and node != function
            for node in _walk(function)
        ):
            return source, "nested functions or closures are skipped"
        params = function.child_by_field_name("parameters")
        body = function.child_by_field_name("body")
        if params is None or body is None:
            return source, "function has unsupported syntax"
        params_nodes = list(params.named_children)
        if any(node.type != "required_parameter" for node in params_nodes):
            return source, "optional, default, or destructured parameters are skipped"
        for param in params_nodes:
            pattern = param.child_by_field_name("pattern")
            if pattern is None or pattern.type != "identifier":
                return source, "destructured parameters are skipped"
            name = pattern.text.decode()
            if any(
                node.type == "shorthand_property_identifier"
                and node.text.decode() == name
                for node in _walk(body)
            ):
                return (
                    source,
                    "shorthand object properties are skipped during parameter renaming",
                )
            candidate = f"p{rng.randrange(0, 10_000)}"
            while candidate in occupied:
                candidate = f"p{rng.randrange(0, 10_000)}"
            occupied.add(candidate)
            edits.append((pattern.start_byte, pattern.end_byte, candidate))
            edits.extend(
                (node.start_byte, node.end_byte, candidate)
                for node in _walk(body)
                if node.type == "identifier"
                and node.text.decode() == name
                and _is_value_reference(node)
            )
    return _apply_edits(source, edits), None


def _is_value_reference(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type in {"property_identifier", "type_identifier", "type_annotation"}:
        return False
    return not (
        parent.type == "member_expression"
        and parent.child_by_field_name("property") == node
    )


def _safe_to_reorder(root: Node, functions: list[FunctionRecord]) -> bool:
    root_functions = [
        node
        for node in root.named_children
        if node.type == "function_declaration"
        or (
            node.type == "export_statement"
            and node.child_by_field_name("declaration") is not None
            and node.child_by_field_name("declaration").type == "function_declaration"
        )
    ]
    return len(root_functions) == len(root.named_children) == len(functions) and all(
        not any(
            child.type in {"decorator", "comment"}
            for child in _walk(record.declaration)
        )
        and not any(
            child.type in {"required_parameter", "optional_parameter"}
            and child.child_by_field_name("value")
            for child in _walk(record.declaration)
        )
        for record in functions
    )


def _inline_locals(source: str, root: Node) -> tuple[str, str | None]:
    edits = []
    for record in _functions(root):
        body = record.declaration.child_by_field_name("body")
        if body is None:
            continue
        statements = body.named_children
        for first, second in pairwise(statements):
            declaration = _single_const(first)
            returned = _returned_name(second)
            if declaration is None or returned is None or declaration[0] != returned[0]:
                continue
            name, expression = declaration
            if (
                not _pure_ts_expression(expression)
                or _reference_count(record.declaration, name) != 2
            ):
                continue
            expression_text = _source_slice(
                source, expression.start_byte, expression.end_byte
            )
            edits.append(
                (first.start_byte, second.end_byte, f"return {expression_text};")
            )
            break
    if not edits:
        return source, "no safe adjacent const-return pair found"
    return _apply_edits(source, edits), None


def _single_const(statement: Node) -> tuple[str, Node] | None:
    if (
        statement.type != "lexical_declaration"
        or not statement.text.lstrip().startswith(b"const")
    ):
        return None
    declarators = [
        node for node in statement.named_children if node.type == "variable_declarator"
    ]
    if len(declarators) != 1:
        return None
    name = declarators[0].child_by_field_name("name")
    value = declarators[0].child_by_field_name("value")
    if name is None or name.type != "identifier" or value is None:
        return None
    return name.text.decode(), value


def _returned_name(statement: Node) -> tuple[str, Node] | None:
    if statement.type != "return_statement" or len(statement.named_children) != 1:
        return None
    value = statement.named_children[0]
    return (value.text.decode(), value) if value.type == "identifier" else None


def _pure_ts_expression(node: Node) -> bool:
    allowed = {
        "identifier",
        "number",
        "string",
        "true",
        "false",
        "null",
        "binary_expression",
        "unary_expression",
        "parenthesized_expression",
        "array",
        "object",
        "pair",
    }
    return node.type in allowed and all(
        _pure_ts_expression(child) for child in node.named_children
    )


def _reference_count(function: Node, name: str) -> int:
    return sum(
        node.type == "identifier"
        and node.text.decode() == name
        and _is_value_reference(node)
        for node in _walk(function)
    )


def _all_functions(root: Node) -> list[FunctionRecord]:
    records = []
    for node in _walk(root):
        if node.type == "function_declaration":
            parent = node.parent
            exported = parent is not None and parent.type == "export_statement"
            records.append(
                FunctionRecord(node if not exported else parent, node, exported)
            )
    return records


def _add_dead_branches(source: str, root: Node, rng: random.Random) -> str:
    edits = []
    for record in _all_functions(root):
        body = record.declaration.child_by_field_name("body")
        if body:
            count = rng.randint(1, 3)
            dead = " " + " ".join("if (false) { void 0; }" for _ in range(count)) + " "
            edits.append((body.end_byte - 1, body.end_byte - 1, dead))
    return _apply_edits(source, edits)


def _wrap_in_class(source: str, root: Node) -> tuple[str, str | None]:
    functions = _functions(root)
    if not functions:
        return source, "no top-level function declarations found"
    names = {
        record.declaration.child_by_field_name("name").text.decode()
        for record in functions
    }
    reason = _class_conversion_skip_reason(root, functions, names)
    if reason:
        return source, reason
    methods = []
    aliases = []
    class_name = _fresh_identifier(root, "MutationContainer")
    for record in functions:
        function = record.declaration
        name = function.child_by_field_name("name")
        body = function.child_by_field_name("body")
        if name is None or body is None:
            return source, "function has unsupported syntax"
        body_text = _source_slice(source, body.start_byte, body.end_byte)
        edits = []
        for node in _walk(body):
            if node.type == "call_expression":
                callee = node.child_by_field_name("function")
                if (
                    callee
                    and callee.type == "identifier"
                    and callee.text.decode() in names
                ):
                    target = callee.text.decode()
                    edits.append(
                        (
                            callee.start_byte - body.start_byte,
                            callee.end_byte - body.start_byte,
                            f"{class_name}.{target}",
                        )
                    )
        body_text = _apply_edits(body_text, edits)
        method_tail = _source_slice(source, name.start_byte, body.start_byte)
        methods.append(f"  static {method_tail}{body_text}")
        aliases.append(
            f"export const {name.text.decode()} = {class_name}.{name.text.decode()};"
            if record.exported
            else f"const {name.text.decode()} = {class_name}.{name.text.decode()};"
        )
    retained = _apply_edits(
        source,
        [(record.node.start_byte, record.node.end_byte, "") for record in functions],
    )
    class_text = f"\nclass {class_name} {{\n" + "\n".join(methods) + "\n}\n"
    return retained.rstrip() + class_text + "\n".join(aliases) + "\n", None


def _class_conversion_skip_reason(
    root: Node, functions: list[FunctionRecord], names: set[str]
) -> str | None:
    allowed_top_level = {
        "function_declaration",
        "export_statement",
        "import_statement",
        "comment",
    }
    if any(node.type not in allowed_top_level for node in root.named_children):
        return "top-level executable statements cannot be reordered safely"
    if any(
        node.type == "export_statement"
        and node.text.lstrip().startswith(b"export default")
        for node in root.named_children
    ):
        return "default exports cannot be preserved by named static aliases"
    for record in functions:
        function = record.declaration
        parameters = function.child_by_field_name("parameters")
        if parameters and any(
            param.child_by_field_name("pattern")
            and param.child_by_field_name("pattern").text.decode() in names
            for param in _walk(parameters)
        ):
            return "parameter shadows a module function"
        if any(
            node.type in {"lexical_declaration", "variable_declaration"}
            and any(
                child.type == "identifier" and child.text.decode() in names
                for child in _walk(node)
            )
            for node in _walk(function)
        ):
            return "local shadows a module function"
        if any(
            node != function
            and node.type
            in {"function_declaration", "arrow_function", "function_expression"}
            for node in _walk(function)
        ):
            return "nested function scopes are skipped by class wrapping"
        prefix = _source_slice(
            root.text.decode(),
            function.start_byte,
            function.child_by_field_name("name").start_byte,
        )
        if "async" in prefix or "*" in prefix:
            return "async and generator functions are skipped by class wrapping"
    return None


def _loops_to_recursion(source: str, root: Node) -> tuple[str, str | None]:
    records = _functions(root)
    if len(records) != 1:
        return source, "expected one top-level function"
    function = records[0].declaration
    loop, reason = _find_loop(function)
    if reason:
        return source, reason
    plan = _validate_loop(function, loop)
    if isinstance(plan, str):
        return source, plan
    fresh = _fresh_identifier(root, "_mutate_step")
    helper = (
        f"const {fresh} = (index: number, value: typeof {plan.accumulator}): "
        f"typeof {plan.accumulator} => "
        f"index >= {plan.iterable}.length ? value : {fresh}(index + 1, "
        f"value + {plan.iterable}[index]);"
    )
    replacement = f"{helper} {plan.accumulator} = {fresh}(0, {plan.accumulator});"
    return _apply_edits(
        source, [(plan.loop.start_byte, plan.loop.end_byte, replacement)]
    ), None


def _find_loop(function: Node) -> tuple[Node | None, str | None]:
    loops = [
        node
        for node in _walk(function)
        if node.type in {"for_in_statement", "for_statement", "while_statement"}
    ]
    if len(loops) != 1:
        return None, "expected one loop; multiple or missing loops are skipped"
    loop = loops[0]
    if loop.type == "while_statement":
        return None, "while loop conversion is not supported"
    if loop.type == "for_statement":
        return None, "only for-of accumulator loops are supported"
    return loop, None


def _validate_loop(function: Node, loop: Node | None) -> LoopPlan | str:
    if loop is None:
        return "no supported loop found"
    body = function.child_by_field_name("body")
    statements = body.named_children if body else []
    if len(statements) != 3 or statements[1] != loop:
        return "only a direct accumulator for-of loop is supported"
    declaration, _, returned = statements
    declarators = [
        node
        for node in declaration.named_children
        if node.type == "variable_declarator"
    ]
    if not declaration.text.lstrip().startswith(b"let") or len(declarators) != 1:
        return "accumulator must be initialized with one let declaration"
    accumulator = declarators[0].child_by_field_name("name")
    iterable = loop.child_by_field_name("right")
    target = loop.child_by_field_name("left")
    loop_body = loop.child_by_field_name("body")
    body_statements = loop_body.named_children if loop_body else []
    valid_identifiers = all(
        node is not None and node.type == "identifier"
        for node in (accumulator, iterable, target)
    )
    if not valid_identifiers or len(body_statements) != 1:
        return "loop must have simple identifiers and one accumulator update"
    if not _array_parameter(function, iterable.text.decode()):
        return "for-of iterable must be a typed array parameter"
    update = (
        body_statements[0].named_children[0]
        if body_statements[0].named_children
        else None
    )
    left = update.child_by_field_name("left") if update else None
    right = update.child_by_field_name("right") if update else None
    operator = update.child_by_field_name("operator") if update else None
    valid_update = (
        update is not None
        and update.type == "augmented_assignment_expression"
        and left is not None
        and right is not None
        and operator is not None
        and left.text == accumulator.text
        and right.text == target.text
        and operator.text == b"+="
    )
    if not valid_update:
        return "only accumulator += loop-item is supported"
    returned_value = (
        returned.named_children[0]
        if returned.type == "return_statement" and returned.named_children
        else None
    )
    if returned_value is None or returned_value.text != accumulator.text:
        return "function must return the accumulator immediately after the loop"
    return LoopPlan(loop, iterable.text.decode(), accumulator.text.decode())


def _array_parameter(function: Node, name: str) -> bool:
    params = function.child_by_field_name("parameters")
    if params is None:
        return False
    for param in params.named_children:
        pattern = param.child_by_field_name("pattern")
        type_node = param.child_by_field_name("type")
        if (
            pattern
            and pattern.text.decode() == name
            and type_node
            and any(node.type == "array_type" for node in _walk(type_node))
        ):
            return True
    return False


def _fresh_identifier(root: Node, stem: str) -> str:
    names = {node.text.decode() for node in _walk(root) if node.type == "identifier"}
    candidate = stem
    index = 0
    while candidate in names:
        index += 1
        candidate = f"{stem}_{index}"
    return candidate


def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    result = source.encode()
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement.encode() + result[end:]
    return result.decode()


def _source_slice(source: str, start: int, end: int) -> str:
    return source.encode()[start:end].decode()
