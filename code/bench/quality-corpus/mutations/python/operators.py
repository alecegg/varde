"""Conservative, behavior-aware Python held-out mutations."""

from __future__ import annotations

import ast
import copy
import random

from ..core import Mutation, make_mutation, parses, random_for, stable_seed

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
        raise ValueError(f"unknown Python mutation operator: {operator}")
    tree = ast.parse(source)
    resolved_seed = stable_seed(operator, source, seed)
    rng = random_for(operator, source, resolved_seed)
    skip_reason: str | None = None
    if operator == "reorder-and-rename":
        skip_reason = _reorder_and_rename(tree, rng)
    elif operator == "inline-all-locals":
        changed = _inline_locals(tree)
        skip_reason = (
            None if changed else "no safe single-use straight-line local found"
        )
    elif operator == "add-dead-branches":
        changed = _add_dead_branches(tree, rng)
        skip_reason = None if changed else "no top-level function found"
    elif operator == "wrap-in-class":
        skip_reason = _wrap_in_class(tree)
    else:
        skip_reason = _loops_to_recursion(tree)
    result = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
    if skip_reason is None and result == source:
        skip_reason = "operator produced no source change"
    if skip_reason is None and not parses("python", result):
        raise ValueError("mutation produced invalid Python")
    return make_mutation(
        result if skip_reason is None else source,
        operator,
        OPERATORS[operator],
        pair_group_id,
        resolved_seed,
        skip_reason,
    )


def _reorder_and_rename(tree: ast.Module, rng: random.Random) -> str | None:
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not functions:
        return "no top-level functions found"
    identifiers = _identifiers(tree)
    for function in functions:
        for scoped_function in _function_scopes(function):
            reason = _rename_skip_reason(tree, scoped_function)
            if reason:
                return reason
            _rename_function(scoped_function, identifiers, rng)
    top_level_is_functions = len(functions) == len(tree.body)
    reorder_safe = top_level_is_functions and all(
        not fn.decorator_list
        and not fn.args.defaults
        and not fn.args.kw_defaults
        and all(arg.annotation is None for arg in [*fn.args.posonlyargs, *fn.args.args])
        and fn.returns is None
        for fn in functions
    )
    if reorder_safe and len(functions) > 1:
        order = list(functions)
        rng.shuffle(order)
        if order == functions:
            order.reverse()
        iterator = iter(order)
        tree.body = [next(iterator) for _ in tree.body]
    return None


def _rename_skip_reason(
    tree: ast.Module, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> str | None:
    descendants = list(ast.walk(function))
    if any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in descendants):
        return f"skipped {function.name}: global/nonlocal binding"
    if any(isinstance(node, ast.Lambda) for node in descendants):
        return f"skipped {function.name}: lambda closure"
    if _has_closure(function):
        return f"skipped {function.name}: nested closure"
    if function.args.defaults or function.args.kw_defaults:
        return (
            f"skipped {function.name}: default arguments may depend on definition order"
        )
    if function.decorator_list:
        return f"skipped {function.name}: decorators may depend on definition order"
    if function.args.kwonlyargs or function.args.vararg or function.args.kwarg:
        return f"skipped {function.name}: keyword or variadic parameters"
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if (
            isinstance(call.func, ast.Name)
            and call.func.id == function.name
            and call.keywords
        ):
            return f"skipped {function.name}: keyword call depends on parameter names"
    return None


def _identifiers(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            values.add(node.id)
        elif isinstance(node, ast.arg):
            values.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values.add(node.name)
    return values


def _function_scopes(function: ast.FunctionDef | ast.AsyncFunctionDef):
    yield function
    for child in _scope_nodes(function):
        if (
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child is not function
        ):
            yield from _function_scopes(child)


def _scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef):
    def visit(node: ast.AST):
        yield node
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    for statement in function.body:
        yield from visit(statement)


def _has_closure(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    parent_locals = {
        node.id
        for node in _scope_nodes(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    parent_locals.update(
        arg.arg for arg in [*function.args.posonlyargs, *function.args.args]
    )
    nested = [
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node is not function
    ]
    for child in nested:
        if any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in parent_locals
            for node in ast.walk(child)
        ):
            return True
    return False


def _rename_function(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    identifiers: set[str],
    rng: random.Random,
) -> None:
    arguments = [*function.args.posonlyargs, *function.args.args]
    local_names = sorted(
        {
            node.id
            for node in _scope_nodes(function)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        - {arg.arg for arg in arguments}
    )
    mapping: dict[str, str] = {}
    for prefix, names in (("p", [arg.arg for arg in arguments]), ("v", local_names)):
        offset = rng.randrange(0, 10_000)
        for index, name in enumerate(names):
            candidate = f"{prefix}{offset + index}"
            while candidate in identifiers or candidate in mapping.values():
                offset += 1
                candidate = f"{prefix}{offset + index}"
            mapping[name] = candidate
            identifiers.add(candidate)
    for argument in arguments:
        argument.arg = mapping[argument.arg]
    for node in _scope_nodes(function):
        if isinstance(node, ast.Name) and node.id in mapping:
            node.id = mapping[node.id]


def _inline_locals(tree: ast.Module) -> bool:
    changed = False
    for function in (
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        if any(
            isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(function)
        ):
            continue
        if len(function.body) < 2 or any(
            isinstance(
                node,
                (
                    ast.If,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.Try,
                    ast.With,
                    ast.AsyncWith,
                    ast.Match,
                    ast.Lambda,
                ),
            )
            for node in ast.walk(function)
        ):
            continue
        replacements: dict[str, ast.expr] = {}
        kept: list[ast.stmt] = []
        statements = function.body
        index = 0
        while index < len(statements):
            assignment = statements[index]
            following = statements[index + 1] if index + 1 < len(statements) else None
            candidate = _inline_candidate(function, assignment, following)
            if candidate:
                name, expression, returned = candidate
                replacements[name] = expression
                kept.append(returned)
                index += 2
                changed = True
                continue
            kept.append(assignment)
            index += 1
        for statement in kept:
            _replace_loads(statement, replacements)
        function.body = kept
    return changed


def _inline_candidate(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    assignment: ast.stmt,
    following: ast.stmt | None,
) -> tuple[str, ast.expr, ast.Return] | None:
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and isinstance(following, ast.Return)
        and isinstance(following.value, ast.Name)
        and following.value.id == assignment.targets[0].id
        and _pure_expression(assignment.value)
    ):
        return None
    name = assignment.targets[0].id
    stores = sum(
        isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Store)
        for node in ast.walk(function)
    )
    loads = sum(
        isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Load)
        for node in ast.walk(function)
    )
    deletes = any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Del)
        for node in ast.walk(function)
    )
    if stores != 1 or loads != 1 or deletes:
        return None
    returned = copy.deepcopy(following)
    returned.value = copy.deepcopy(assignment.value)
    return name, copy.deepcopy(assignment.value), returned


def _pure_expression(node: ast.expr) -> bool:
    allowed = (
        ast.Name,
        ast.Constant,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.IfExp,
        ast.Tuple,
        ast.List,
    )
    return isinstance(node, allowed) and all(
        _pure_expression(child)
        for child in ast.iter_child_nodes(node)
        if isinstance(child, ast.expr)
    )


def _replace_loads(statement: ast.stmt, replacements: dict[str, ast.expr]) -> None:
    class Replace(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            if isinstance(node.ctx, ast.Load) and node.id in replacements:
                return ast.copy_location(copy.deepcopy(replacements[node.id]), node)
            return node

    Replace().visit(statement)


def _add_dead_branches(tree: ast.Module, rng: random.Random) -> bool:
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for function in functions:
        for _ in range(rng.randint(1, 3)):
            function.body.append(
                ast.If(test=ast.Constant(False), body=[ast.Pass()], orelse=[])
            )
    return bool(functions)


def _wrap_in_class(tree: ast.Module) -> str | None:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if not functions:
        return "no top-level synchronous functions found"
    if len(functions) != len(tree.body):
        return (
            "module has top-level statements whose execution order cannot be preserved"
        )
    names = {function.name for function in functions}
    if "staticmethod" in names:
        return "staticmethod name shadows the descriptor used by class wrapping"
    for function in functions:
        if (
            function.decorator_list
            or function.args.defaults
            or function.args.kw_defaults
            or function.returns is not None
            or any(
                arg.annotation is not None
                for arg in [*function.args.posonlyargs, *function.args.args]
            )
        ):
            return (
                f"skipped {function.name}: decorators, annotations, or defaults "
                "depend on module scope"
            )
        if any(
            isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(function)
        ):
            return f"skipped {function.name}: global/nonlocal binding"
        local_names = {
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        local_names.update(arg.arg for arg in function.args.args)
        local_names.update(
            node.arg for node in ast.walk(function) if isinstance(node, ast.arg)
        )
        if local_names & names:
            return f"skipped {function.name}: local shadows a module function"
    class_name = _fresh_name(tree, "MutationContainer")
    methods = []
    for function in functions:
        _qualify_function_calls(function, names, class_name)
        function.decorator_list.append(ast.Name(id="staticmethod", ctx=ast.Load()))
        methods.append(function)
    tree.body = [
        ast.ClassDef(class_name, [], [], methods, []),
        *[
            ast.Assign(
                targets=[ast.Name(id=function.name, ctx=ast.Store())],
                value=ast.Attribute(
                    value=ast.Name(id=class_name, ctx=ast.Load()),
                    attr=function.name,
                    ctx=ast.Load(),
                ),
            )
            for function in functions
        ],
    ]
    return None


def _qualify_function_calls(
    function: ast.FunctionDef, names: set[str], class_name: str
) -> None:
    class Qualify(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            if isinstance(node.ctx, ast.Load) and node.id in names:
                return ast.copy_location(
                    ast.Attribute(
                        value=ast.Name(id=class_name, ctx=ast.Load()),
                        attr=node.id,
                        ctx=ast.Load(),
                    ),
                    node,
                )
            return node

    Qualify().visit(function)


def _loops_to_recursion(tree: ast.Module) -> str | None:
    if any(
        (
            isinstance(node, ast.Name)
            and node.id in {"iter", "next", "StopIteration"}
            and isinstance(node.ctx, ast.Store)
        )
        or (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name in {"iter", "next", "StopIteration"}
        )
        for node in ast.walk(tree)
    ):
        return "loop helper built-ins are shadowed in this source"
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if len(functions) != 1:
        return "expected one top-level function"
    function = functions[0]
    loops = [
        node for node in ast.walk(function) if isinstance(node, (ast.For, ast.While))
    ]
    if not loops:
        return "no loop found"
    if len(loops) != 1 or isinstance(loops[0], ast.While):
        return "while and nested/multiple loops are not supported"
    loop = loops[0]
    if not isinstance(loop, ast.For) or not _supported_accumulator_loop(function, loop):
        return "loop is not a single accumulator over a for-iterable"
    body_index = function.body.index(loop)
    init = function.body[body_index - 1]
    accumulator = init.targets[0].id
    item_name = loop.target.id
    iterable = loop.iter
    augassign = loop.body[0]
    function_name = _fresh_name(function, "_mutate_step")
    value_name = _fresh_name(function, "_mutate_value")
    iterator_name = _fresh_name(function, "_mutate_iterator")
    item_name = _fresh_name(function, "_mutate_item")
    update = _accumulator_expression(
        augassign.op, ast.Name(value_name, ast.Load()), augassign.value
    )
    update = _replace_expression_names(
        update,
        {
            loop.target.id: ast.Name(item_name, ast.Load()),
            accumulator: ast.Name(value_name, ast.Load()),
        },
    )
    helper = ast.FunctionDef(
        name=function_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(value_name)],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=[
            ast.Try(
                body=[
                    ast.Assign(
                        [ast.Name(item_name, ast.Store())],
                        ast.Call(
                            ast.Name("next", ast.Load()),
                            [ast.Name(iterator_name, ast.Load())],
                            [],
                        ),
                    )
                ],
                handlers=[
                    ast.ExceptHandler(
                        ast.Name("StopIteration", ast.Load()),
                        None,
                        [ast.Return(ast.Name(value_name, ast.Load()))],
                    )
                ],
                orelse=[],
                finalbody=[],
            ),
            ast.Return(
                ast.Call(
                    ast.Name(function_name, ast.Load()),
                    [update],
                    [],
                )
            ),
        ],
        decorator_list=[],
    )
    iterator = ast.Assign(
        [ast.Name(iterator_name, ast.Store())],
        ast.Call(ast.Name("iter", ast.Load()), [copy.deepcopy(iterable)], []),
    )
    call = ast.Assign(
        [ast.Name(accumulator, ast.Store())],
        ast.Call(
            ast.Name(function_name, ast.Load()), [ast.Name(accumulator, ast.Load())], []
        ),
    )
    function.body[body_index - 1 : body_index + 1] = [init, iterator, helper, call]
    return None


def _supported_accumulator_loop(
    function: ast.FunctionDef | ast.AsyncFunctionDef, loop: ast.For
) -> bool:
    if len(function.body) != 3 or loop.orelse or len(loop.body) != 1:
        return False
    init, _, returned = function.body
    return (
        isinstance(init, ast.Assign)
        and len(init.targets) == 1
        and isinstance(init.targets[0], ast.Name)
        and isinstance(init.value, ast.Constant)
        and isinstance(loop.target, ast.Name)
        and isinstance(loop.body[0], ast.AugAssign)
        and type(loop.body[0].op)
        in {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod}
        and isinstance(loop.body[0].target, ast.Name)
        and loop.body[0].target.id == init.targets[0].id
        and _pure_expression(loop.body[0].value)
        and _pure_expression(loop.iter)
        and isinstance(returned, ast.Return)
        and isinstance(returned.value, ast.Name)
        and returned.value.id == init.targets[0].id
        and not any(
            isinstance(node, (ast.Break, ast.Continue, ast.Await, ast.Yield))
            for node in ast.walk(loop)
        )
        and not any(
            isinstance(node, ast.Name) and node.id in {"iter", "next", "StopIteration"}
            for node in ast.walk(function)
        )
    )


def _accumulator_expression(
    operator: ast.operator, accumulator: ast.expr, value: ast.expr
) -> ast.expr:
    mapped = {
        ast.Add: ast.Add,
        ast.Sub: ast.Sub,
        ast.Mult: ast.Mult,
        ast.Div: ast.Div,
        ast.FloorDiv: ast.FloorDiv,
        ast.Mod: ast.Mod,
    }
    operator_type = mapped.get(type(operator))
    if operator_type is None:
        raise ValueError(f"unsupported accumulator operator: {type(operator).__name__}")
    return ast.BinOp(accumulator, operator_type(), copy.deepcopy(value))


def _replace_expression_names(
    node: ast.expr, replacements: dict[str, ast.expr]
) -> ast.expr:
    class Replace(ast.NodeTransformer):
        def visit_Name(self, child: ast.Name) -> ast.AST:
            if child.id in replacements and isinstance(child.ctx, ast.Load):
                return copy.deepcopy(replacements[child.id])
            return child

    return Replace().visit(node)


def _fresh_name(node: ast.AST, stem: str) -> str:
    used = _identifiers(node)
    index = 0
    candidate = stem
    while candidate in used:
        index += 1
        candidate = f"{stem}_{index}"
    return candidate
