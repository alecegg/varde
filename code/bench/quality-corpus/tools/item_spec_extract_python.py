from __future__ import annotations

import ast

from item_spec_cognitive import python_cognitive
from item_spec_extract_types import TOKEN, Function


def _python(source: str) -> list[Function]:
    tree = ast.parse(source)
    data = source.encode()
    offsets = _line_offsets(source)
    found = _python_functions(tree)
    is_extracted = _python_scorer(frozenset(id(node) for _, _, node in found))
    functions = [
        _python_function(name, node, data, offsets, is_extracted)
        for _, name, node in found
    ]
    names = {function.name for function in functions}
    class_methods = {
        node.name
        for cls in (item for item in ast.walk(tree) if isinstance(item, ast.ClassDef))
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    constructors = {
        node.name: [
            member.name
            for member in node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and (
                member.name == "__init__"
                or (member.name.startswith("__") and member.name.endswith("__"))
            )
        ]
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name in {"__init__", "__new__"}
            for member in node.body
        )
    }
    extracted = {id(node) for _, _, node in found}
    for (_, _, node), function in zip(found, functions, strict=True):
        shadowed = _python_local_names(node, is_extracted)
        direct_calls = _python_call_kinds(node, extracted, shadowed)
        direct_calls.update(_python_method_calls(node, class_methods, constructors))
        references = _python_value_references(node, names, extracted, shadowed)
        function.edges = sorted((direct_calls | set(references)) - shadowed)
    return functions


def _python_local_names(node, is_extracted):
    arguments = (
        node.args
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        else None
    )
    names = set()
    if arguments:
        names.update(arg.arg for arg in _python_args(arguments))
    globals_ = set()

    pending = _python_body_nodes(node)
    while pending:
        current = pending.pop()
        if is_extracted(current):
            names.update(_extracted_local_name(current))
            continue
        if isinstance(current, (ast.Lambda, ast.comprehension)):
            continue
        if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Store):
            names.add(current.id)
        if isinstance(current, ast.Global):
            globals_.update(current.names)
        if isinstance(current, ast.Nonlocal):
            names.update(current.names)
        pending.extend(ast.iter_child_nodes(current))
    return names - globals_


def _extracted_local_name(node):
    name = getattr(node, "name", None)
    return {name} if name is not None else set()


def _python_call_kinds(node, extracted, shadowed):
    direct = set()
    pending = _python_body_nodes(node)
    while pending:
        current = pending.pop()
        if id(current) in extracted:
            continue
        if (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Name)
            and current.func.id not in shadowed
        ):
            direct.add(current.func.id)
        pending.extend(ast.iter_child_nodes(current))
    return direct


def _python_method_calls(node, methods, constructors):
    calls = set()
    pending = _python_body_nodes(node)
    while pending:
        current = pending.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Call):
            target = current.func
            if (
                isinstance(target, ast.Attribute)
                and target.attr in methods
                and (
                    isinstance(target.value, ast.Name)
                    and target.value.id in {"self", "this"}
                    or isinstance(target.value, ast.Call)
                    and isinstance(target.value.func, ast.Name)
                    and target.value.func.id in constructors
                )
            ):
                calls.add(target.attr)
            elif isinstance(target, ast.Name) and target.id in constructors:
                calls.update(constructors[target.id])
        pending.extend(ast.iter_child_nodes(current))
    return calls


def _python_value_references(node, names, extracted, shadowed):
    references = set()
    pending = [(child, shadowed) for child in _python_body_nodes(node)]
    while pending:
        current, local_names = pending.pop()
        if id(current) in extracted:
            pending.extend(_nested_definition_defaults(current, shadowed))
            continue
        if _is_free_function_name(current, names, local_names):
            references.add(current.id)
        scoped = _python_scoped_children(current, local_names, node)
        pending.extend(scoped)
    return sorted(references)


def _python_body_nodes(node):
    body = (
        node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else node
    )
    return list(body) if isinstance(body, list) else [body]


def _nested_definition_defaults(node, local_names):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    expressions = [*node.decorator_list, *node.args.defaults]
    expressions.extend(value for value in node.args.kw_defaults if value is not None)
    return [(expression, local_names) for expression in expressions]


def _is_free_function_name(node, names, local_names):
    return (
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in names
        and node.id not in local_names
    )


def _python_scoped_children(node, local_names, root):
    if isinstance(node, ast.Lambda) and node is not root:
        bindings = {arg.arg for arg in _python_args(node.args)}
        return [(node.body, local_names | bindings)]
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _comprehension_children(node, local_names)
    if isinstance(node, ast.comprehension):
        return _generator_children(node, local_names)
    return [(child, local_names) for child in ast.iter_child_nodes(node)]


def _comprehension_children(node, local_names):
    result = []
    bound = local_names
    for generator in node.generators:
        result.append((generator.iter, bound))
        bound = bound | _target_names(generator.target)
        result.extend((condition, bound) for condition in generator.ifs)
    values = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
    result.extend((value, bound) for value in values)
    return result


def _generator_children(node, local_names):
    bound = local_names | _target_names(node.target)
    return [(node.iter, local_names), *((condition, bound) for condition in node.ifs)]


def _target_names(node):
    return {target.id for target in ast.walk(node) if isinstance(target, ast.Name)}


def _python_scorer(extracted: frozenset[int]):
    def is_extracted(node: ast.AST) -> bool:
        return (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or id(node) in extracted
        )

    return is_extracted


def _python_functions(tree: ast.AST) -> list[tuple[tuple[int, int], str, ast.AST]]:
    found = [
        (position, name, _function_node(node))
        for node in ast.walk(tree)
        if (position := _function_position(node)) is not None
        if (name := _function_name(node)) is not None
    ]
    return sorted(found, key=lambda item: item[0])


def _function_position(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.lineno, node.col_offset
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
        node.value, ast.Lambda
    ):
        return node.lineno, node.col_offset
    return None


def _function_name(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
        node.value, ast.Lambda
    ):
        return _target_name(node)
    return None


def _function_node(node):
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
        node.value, ast.Lambda
    ):
        return node.value
    return node


def _python_function(
    name: str, node: ast.AST, data: bytes, offsets: list[int], is_extracted
) -> Function:
    start, end = _span(node, offsets)
    own = bytearray(data[start:end])
    for nested_start, nested_end in _nested_spans(node, offsets, is_extracted):
        own[nested_start - start : nested_end - start] = b" " * (
            nested_end - nested_start
        )
    calls = _python_calls(node, is_extracted)
    return Function(
        name,
        len(TOKEN.findall(own.decode())),
        node.end_lineno - node.lineno + 1,
        calls,
        python_cognitive(node, is_extracted) + sum(call == name for call in calls),
        _python_signature(node),
    )


def _python_signature(node: ast.AST) -> str:
    args = ast.dump(node.args, include_attributes=False)
    returned = getattr(node, "returns", None)
    if returned is None:
        return args
    return f"{args} -> {ast.dump(returned, include_attributes=False)}"


def _python_calls(node: ast.AST, is_extracted) -> list[str]:
    calls: list[str] = []
    pending = list(reversed(list(ast.iter_child_nodes(node))))
    while pending:
        current = pending.pop()
        if is_extracted(current):
            continue
        target = _call_target(current.func) if isinstance(current, ast.Call) else None
        if target:
            calls.append(target)
        pending.extend(reversed(list(ast.iter_child_nodes(current))))
    return calls


def _python_args(arguments):
    return (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *((arguments.vararg,) if arguments.vararg else ()),
        *((arguments.kwarg,) if arguments.kwarg else ()),
    )


def _call_target(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _nested_spans(
    node: ast.AST, offsets: list[int], is_extracted
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pending = list(reversed(list(ast.iter_child_nodes(node))))
    while pending:
        current = pending.pop()
        if is_extracted(current):
            spans.append(_span(current, offsets))
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(current))))
    return spans


def _target_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return next((target.id for target in targets if isinstance(target, ast.Name)), None)


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode()))
    return offsets


def _span(node: ast.AST, offsets: list[int]) -> tuple[int, int]:
    return (
        offsets[node.lineno - 1] + node.col_offset,
        offsets[node.end_lineno - 1] + node.end_col_offset,
    )
