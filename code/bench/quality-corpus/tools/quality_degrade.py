"""Deterministic, behaviour-preserving quality degradations of Python source.

Each degradation maps source text to source text with the same observable
behaviour for positional callers (comments are lost: ``ast.unparse``). A result
equal to the unparsed input is a no-op for that source and is dropped by the
caller. No randomness, no model call.

* ``inline_helpers``: inline private helpers into their callers (monolith);
* ``guard_nesting``: turn guard clauses into ``if/else`` pyramids;
* ``rename_vague``: private names and locals become ``data``, ``tmp``, ``x1``;
* ``add_params``: three unneeded defaulted parameters on every function;
* ``wrappers``: every function delegates to one trivial one-line wrapper;
* ``deep_chain``: every function delegates through a chain of four wrappers;
* ``compound``: inline, then vague names, then extra parameters.
"""

from __future__ import annotations

import ast
import copy
from collections.abc import Callable
from typing import NamedTuple

FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
TERMINALS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
VAGUE = ("data", "tmp", "val", "res", "obj", "item", "info", "thing", "stuff")
EXTRA_PARAMS = ("flag", "options", "context")
MAX_PASSES = 8
CHAIN_DEPTH = 4


def render(tree: ast.AST) -> str:
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def is_private(name: str) -> bool:
    return name.startswith("_") and not is_dunder(name) and name != "_"


def vague_name(index: int) -> str:
    return VAGUE[index] if index < len(VAGUE) else f"x{index - len(VAGUE) + 1}"


def decorator_names(node: ast.FunctionDef) -> list[str]:
    return [d.id if isinstance(d, ast.Name) else "?" for d in node.decorator_list]


# ---- guard inversion --------------------------------------------------------


def ends_terminal(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], TERMINALS)


def invert_inside(stmt: ast.stmt) -> ast.stmt:
    for field in ("body", "orelse", "finalbody"):
        block = getattr(stmt, field, None)
        if isinstance(block, list):
            setattr(stmt, field, invert_guards(block))
    for handler in getattr(stmt, "handlers", []):
        handler.body = invert_guards(handler.body)
    return stmt


def invert_guards(body: list[ast.stmt]) -> list[ast.stmt]:
    """Move the statements after ``if c: <terminal>`` into its ``else``."""
    out: list[ast.stmt] = []
    for index, stmt in enumerate(body):
        rest = body[index + 1 :]
        is_guard = (
            isinstance(stmt, ast.If)
            and not stmt.orelse
            and ends_terminal(stmt.body)
            and bool(rest)
        )
        if not is_guard:
            out.append(invert_inside(stmt))
            continue
        stmt.body = invert_guards(stmt.body)
        stmt.orelse = invert_guards(rest)
        out.append(stmt)
        break
    return out


def guard_nesting(source: str) -> str:
    tree = ast.parse(source)
    tree.body = invert_guards(tree.body)
    return render(tree)


# ---- inlining ---------------------------------------------------------------


class Helper(NamedTuple):
    name: str
    params: list[str]
    body: list[ast.stmt]
    static: bool


def strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0]
    is_doc = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    return body[1:] if is_doc else body


def has_return(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Return) for n in ast.walk(node))


def tail_returns_only(body: list[ast.stmt]) -> bool:
    for index, stmt in enumerate(body):
        last = index == len(body) - 1
        if isinstance(stmt, ast.Return):
            if not last:
                return False
        elif isinstance(stmt, ast.If) and last:
            if not (tail_returns_only(stmt.body) and tail_returns_only(stmt.orelse)):
                return False
        elif has_return(stmt):
            return False
    return True


def always_returns(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    last = body[-1]
    if isinstance(last, ast.Return):
        return True
    return (
        isinstance(last, ast.If)
        and always_returns(last.body)
        and always_returns(last.orelse)
    )


def uses_unsupported(node: ast.FunctionDef) -> bool:
    banned = (
        ast.Yield,
        ast.YieldFrom,
        ast.Await,
        ast.Global,
        ast.Nonlocal,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    inner = [n for stmt in node.body for n in ast.walk(stmt)]
    return any(isinstance(n, banned) for n in inner)


def calls_itself(node: ast.FunctionDef) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == node.name:
            return True
        if isinstance(n, ast.Attribute) and n.attr == node.name:
            return True
    return False


def as_helper(node: ast.AST) -> Helper | None:
    if not isinstance(node, ast.FunctionDef) or not is_private(node.name):
        return None
    a = node.args
    plain = not (a.vararg or a.kwarg or a.kwonlyargs or a.defaults or a.kw_defaults)
    names = decorator_names(node)
    static = names == ["staticmethod"]
    if not plain or (names and not static):
        return None
    if uses_unsupported(node) or calls_itself(node):
        return None
    body = strip_docstring(node.body) or [ast.Pass()]
    if not tail_returns_only(body):
        body = invert_guards(copy.deepcopy(body))
    if not tail_returns_only(body):
        return None
    params = [arg.arg for arg in a.posonlyargs + a.args]
    return Helper(node.name, params, body, static)


def is_simple(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name | ast.Constant):
        return True
    return isinstance(expr, ast.Attribute) and is_simple(expr.value)


class Renamer(ast.NodeTransformer):
    """Replace names by expressions (parameters) or fresh names (locals)."""

    def __init__(self, mapping: dict[str, ast.expr]) -> None:
        self.mapping = mapping

    def visit_Name(self, node: ast.Name) -> ast.expr:
        target = self.mapping.get(node.id)
        if target is None:
            return node
        if isinstance(target, ast.Name):
            return ast.copy_location(ast.Name(target.id, node.ctx), node)
        return copy.deepcopy(target)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        target = self.mapping.get(node.arg)
        if isinstance(target, ast.Name):
            node.arg = target.id
        return node


class ReturnRewriter(ast.NodeTransformer):
    def __init__(self, make: Callable[[ast.expr | None], list[ast.stmt]]) -> None:
        self.make = make

    def visit_Return(self, node: ast.Return) -> list[ast.stmt]:
        return self.make(node.value)


def stored_names(body: list[ast.stmt]) -> set[str]:
    found: set[str] = set()
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                found.add(n.id)
            if isinstance(n, ast.Lambda):
                found.update(arg.arg for arg in n.args.args)
    return found


def param_mapping(
    helper: Helper, args: list[ast.expr], core: str
) -> tuple[dict[str, ast.expr], list[ast.stmt]]:
    stored = stored_names(helper.body)
    mapping: dict[str, ast.expr] = {}
    prologue: list[ast.stmt] = []
    for param, arg in zip(helper.params, args, strict=True):
        if is_simple(arg) and param not in stored:
            mapping[param] = arg
            continue
        fresh = ast.Name(f"{core}_{param}", ast.Load())
        prologue.append(
            ast.Assign([ast.Name(fresh.id, ast.Store())], copy.deepcopy(arg), None)
        )
        mapping[param] = fresh
    for name in stored - set(helper.params):
        mapping[name] = ast.Name(f"{core}_{name}", ast.Load())
    return mapping, prologue


def sink_stmts(value: ast.expr | None, sink: ast.stmt | None) -> list[ast.stmt]:
    """Statement that takes the place of ``return value`` for a call site."""
    if isinstance(sink, ast.Assign):
        constant = value if value is not None else ast.Constant(None)
        return [ast.Assign(copy.deepcopy(sink.targets), constant, None)]
    if isinstance(sink, ast.Return):
        return [ast.Return(value)]
    if value is None or isinstance(value, ast.Constant):
        return [ast.Pass()]
    return [ast.Expr(value)]


def expand(helper: Helper, args: list[ast.expr], sink: ast.stmt) -> list[ast.stmt]:
    """The helper's body for one call whose result goes to ``sink``."""
    core = helper.name.lstrip("_")
    mapping, prologue = param_mapping(helper, args, core)
    body = Renamer(mapping).visit(ast.Module(copy.deepcopy(helper.body), [])).body
    complete = always_returns(helper.body)
    carries_value = isinstance(sink, ast.Assign) and not complete
    inner_sink = (
        ast.Assign([ast.Name(f"{core}_result", ast.Store())], ast.Constant(None), None)
        if carries_value
        else sink
    )
    body = (
        ReturnRewriter(lambda v: sink_stmts(v, inner_sink))
        .visit(ast.Module(body, []))
        .body
    )
    out = [*prologue, *body]
    if carries_value:
        start = ast.Assign(copy.deepcopy(inner_sink.targets), ast.Constant(None), None)
        end = ast.Assign(
            copy.deepcopy(sink.targets), ast.Name(f"{core}_result", ast.Load()), None
        )
        return [start, *out, end]
    if isinstance(sink, ast.Return) and not complete:
        out.append(ast.Return(ast.Constant(None)))
    return out


class Scope(NamedTuple):
    functions: dict[str, Helper]
    methods: dict[str, Helper]


def resolve(call: ast.expr, scope: Scope) -> Helper | None:
    """The helper a call statically names, with the right arity."""
    if not isinstance(call, ast.Call) or call.keywords:
        return None
    if any(isinstance(a, ast.Starred) for a in call.args):
        return None
    func = call.func
    helper = None
    if isinstance(func, ast.Name):
        helper = scope.functions.get(func.id)
    elif (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    ):
        helper = scope.methods.get(func.attr)
    if helper is None:
        return None
    return helper if len(call_args(call, helper)) == len(helper.params) else None


def call_args(call: ast.Call, helper: Helper) -> list[ast.expr]:
    func = call.func
    receiver = (
        [ast.Name("self", ast.Load())]
        if isinstance(func, ast.Attribute) and not helper.static
        else []
    )
    return [*receiver, *call.args]


def single_return_expr(helper: Helper) -> ast.expr | None:
    if len(helper.body) == 1 and isinstance(helper.body[0], ast.Return):
        return helper.body[0].value
    return None


class ExpressionInliner(ast.NodeTransformer):
    """Substitute calls of single-expression helpers that have simple arguments."""

    def __init__(self, scope: Scope, events: list[str]) -> None:
        self.scope = scope
        self.events = events

    def visit_Call(self, node: ast.Call) -> ast.expr:
        node = self.generic_visit(node)
        helper = resolve(node, self.scope)
        expr = single_return_expr(helper) if helper else None
        if helper is None or expr is None:
            return node
        args = call_args(node, helper)
        if not all(is_simple(a) for a in args):
            return node
        mapping, _ = param_mapping(helper, args, helper.name.lstrip("_"))
        self.events.append(helper.name)
        return Renamer(mapping).visit(copy.deepcopy(expr))


HOIST_FIELDS = {
    ast.Assign: "value",
    ast.AugAssign: "value",
    ast.AnnAssign: "value",
    ast.Return: "value",
    ast.Expr: "value",
    ast.For: "iter",
    ast.If: "test",
}


def inline_statement(
    stmt: ast.stmt, scope: Scope, events: list[str]
) -> list[ast.stmt] | None:
    """Replacement statements when a direct call field of ``stmt`` inlines."""
    field = HOIST_FIELDS.get(type(stmt))
    call = getattr(stmt, field, None) if field else None
    helper = resolve(call, scope) if call is not None else None
    if helper is None:
        return None
    events.append(helper.name)
    args = call_args(call, helper)
    direct = isinstance(stmt, ast.Assign | ast.Return | ast.Expr)
    if direct and not (isinstance(stmt, ast.Assign) and len(stmt.targets) != 1):
        return expand(helper, args, stmt)
    temp = ast.Name(f"{helper.name.lstrip('_')}_value", ast.Store())
    body = expand(helper, args, ast.Assign([temp], ast.Constant(None), None))
    setattr(stmt, field, ast.Name(temp.id, ast.Load()))
    return [*body, stmt]


def inline_block(
    block: list[ast.stmt], scope: Scope, events: list[str]
) -> list[ast.stmt]:
    out: list[ast.stmt] = []
    for stmt in block:
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list) and not isinstance(stmt, FUNCS):
                setattr(stmt, field, inline_block(inner, scope, events))
        for handler in getattr(stmt, "handlers", []):
            handler.body = inline_block(handler.body, scope, events)
        replaced = inline_statement(stmt, scope, events)
        out.extend(replaced if replaced is not None else [stmt])
    return out


def scopes(tree: ast.Module) -> list[tuple[ast.FunctionDef, Scope]]:
    module_helpers = {h.name: h for n in tree.body if (h := as_helper(n)) is not None}
    pairs = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            pairs.append((node, Scope(module_helpers, {})))
        if isinstance(node, ast.ClassDef):
            methods = {h.name: h for n in node.body if (h := as_helper(n)) is not None}
            pairs += [
                (n, Scope(module_helpers, methods))
                for n in node.body
                if isinstance(n, ast.FunctionDef)
            ]
    return pairs


def inline_pass(tree: ast.Module, events: list[str]) -> bool:
    before = len(events)
    for fn, scope in scopes(tree):
        rewriter = ExpressionInliner(scope, events)
        fn.body = [rewriter.visit(stmt) for stmt in fn.body]
        fn.body = inline_block(fn.body, scope, events)
    return len(events) > before


def reference_count(tree: ast.Module, name: str, own: ast.AST) -> int:
    inside = {id(n) for n in ast.walk(own)}
    return sum(
        1
        for n in ast.walk(tree)
        if id(n) not in inside
        and (
            (isinstance(n, ast.Name) and n.id == name)
            or (isinstance(n, ast.Attribute) and n.attr == name)
        )
    )


def drop_unreferenced(tree: ast.Module, candidates: set[str]) -> bool:
    removed = False
    blocks = [tree.body] + [n.body for n in tree.body if isinstance(n, ast.ClassDef)]
    for block in blocks:
        for node in list(block):
            unused = (
                isinstance(node, ast.FunctionDef)
                and node.name in candidates
                and reference_count(tree, node.name, node) == 0
            )
            if unused:
                block.remove(node)
                removed = True
        if not block:
            block.append(ast.Pass())
    return removed


def inline_helpers(source: str) -> str:
    tree = ast.parse(source)
    events: list[str] = []
    for _ in range(MAX_PASSES):
        if not inline_pass(tree, events):
            break
    while drop_unreferenced(tree, set(events)):
        pass
    return render(tree)


# ---- naming and signatures --------------------------------------------------


def private_map(tree: ast.Module) -> dict[str, str]:
    found: list[str] = []
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            name = node.name
        elif isinstance(node, ast.Attribute):
            name = node.attr
        if name and is_private(name) and name not in found:
            found.append(name)
    return {name: f"f{i + 1}" for i, name in enumerate(found)}


class PrivateRenamer(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self.mapping.get(node.id, node.id)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        node.attr = self.mapping.get(node.attr, node.attr)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        node.name = self.mapping.get(node.name, node.name)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self.generic_visit(node)
        node.name = self.mapping.get(node.name, node.name)
        return node


def local_vague_map(fn: ast.FunctionDef) -> dict[str, ast.expr]:
    params = [a.arg for a in ast.walk(fn.args) if isinstance(a, ast.arg)]
    stores = {
        n.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }
    renamable = [
        n
        for n in dict.fromkeys([*params, *sorted(stores)])
        if n not in ("self", "cls", "_")
    ]
    taken = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | set(params)
    mapping: dict[str, ast.expr] = {}
    index = 0
    for name in renamable:
        while vague_name(index) in taken:
            index += 1
        mapping[name] = ast.Name(vague_name(index), ast.Load())
        index += 1
    return mapping


def rename_vague(source: str) -> str:
    tree = ast.parse(source)
    tree = PrivateRenamer(private_map(tree)).visit(tree)
    for fn in [n for n in ast.walk(tree) if isinstance(n, FUNCS)]:
        outer = Renamer(local_vague_map(fn))
        outer.visit(fn.args)
        for stmt in fn.body:
            outer.visit(stmt)
    return render(tree)


def add_params(source: str) -> str:
    tree = ast.parse(source)
    for fn in [n for n in ast.walk(tree) if isinstance(n, FUNCS)]:
        a = fn.args
        taken = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
        extras = [ast.arg(n) for n in EXTRA_PARAMS if n not in taken]
        if a.vararg:
            a.kwonlyargs += extras
            a.kw_defaults += [ast.Constant(None) for _ in extras]
            continue
        a.args += extras
        a.defaults += [ast.Constant(None) for _ in extras]
    return render(tree)


# ---- wrappers ---------------------------------------------------------------


def forwarded_call(fn: ast.FunctionDef, callee: ast.expr, skip: int) -> ast.Call:
    a = fn.args
    positional = (a.posonlyargs + a.args)[skip:]
    args: list[ast.expr] = [ast.Name(x.arg, ast.Load()) for x in positional]
    if a.vararg:
        args.append(ast.Starred(ast.Name(a.vararg.arg, ast.Load()), ast.Load()))
    keywords = [ast.keyword(x.arg, ast.Name(x.arg, ast.Load())) for x in a.kwonlyargs]
    if a.kwarg:
        keywords.append(ast.keyword(None, ast.Name(a.kwarg.arg, ast.Load())))
    return ast.Call(callee, args, keywords)


def wrappable(node: ast.AST) -> bool:
    if not isinstance(node, ast.FunctionDef) or is_dunder(node.name):
        return False
    return set(decorator_names(node)) <= {"staticmethod", "classmethod"}


def chain_defs(fn: ast.FunctionDef, depth: int, owner: str | None) -> list[ast.stmt]:
    names = decorator_names(fn)
    is_static, is_class = "staticmethod" in names, "classmethod" in names
    if owner is None:
        callee = lambda n: ast.Name(n, ast.Load())  # noqa: E731
    elif is_static:
        callee = lambda n: ast.Attribute(ast.Name(owner, ast.Load()), n, ast.Load())  # noqa: E731
    else:
        first = "cls" if is_class else "self"
        callee = lambda n: ast.Attribute(ast.Name(first, ast.Load()), n, ast.Load())  # noqa: E731
    skip = 0 if owner is None or is_static else 1
    steps = [f"_{fn.name}_step{k}" for k in range(1, depth + 1)]
    chain = [fn.name, *steps]
    defs: list[ast.stmt] = []
    for here, nxt in zip(chain, [*steps, None], strict=True):
        clone = copy.deepcopy(fn)
        clone.name = here
        if nxt is not None:
            call = forwarded_call(fn, callee(nxt), skip)
            clone.body = [ast.Return(call)]
        defs.append(clone)
    return defs


def wrap_block(block: list[ast.stmt], depth: int, owner: str | None) -> list[ast.stmt]:
    out: list[ast.stmt] = []
    for node in block:
        if wrappable(node):
            out.extend(chain_defs(node, depth, owner))
            continue
        if isinstance(node, ast.ClassDef) and owner is None:
            node.body = wrap_block(node.body, depth, node.name)
        out.append(node)
    return out


def wrap_functions(source: str, depth: int) -> str:
    tree = ast.parse(source)
    tree.body = wrap_block(tree.body, depth, None)
    return render(tree)


def wrappers(source: str) -> str:
    return wrap_functions(source, 1)


def deep_chain(source: str) -> str:
    return wrap_functions(source, CHAIN_DEPTH)


def compound(source: str) -> str:
    return add_params(rename_vague(inline_helpers(source)))


def identity(source: str) -> str:
    return render(ast.parse(source))


DEGRADATIONS: dict[str, Callable[[str], str]] = {
    "inline_helpers": inline_helpers,
    "guard_nesting": guard_nesting,
    "rename_vague": rename_vague,
    "add_params": add_params,
    "wrappers": wrappers,
    "deep_chain": deep_chain,
    "compound": compound,
}
