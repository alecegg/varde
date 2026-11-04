"""Unused declarations and Python local-variable checks."""

from __future__ import annotations

import ast
import re
from collections import Counter

from item_spec_extract import _tree_name
from varde_code.parse import parse_source

EXEMPT = {
    "python": {"main", "__all__", "pytest_plugins", "setUp", "tearDown"},
    "typescript": {"main", "describe", "it", "test", "expect"},
    "java": {"main", "setUp", "tearDown", "Item"},
    "csharp": {"Main", "SetUp", "TearDown", "Item", "Solution"},
    "go": {"main", "init", "TestMain"},
    "rust": {"main", "test"},
    "cpp": {"main", "std", "setUp", "tearDown"},
}

DECLARATION_KINDS = {
    "typescript": {
        "function_declaration",
        "function_signature",
        "variable_declarator",
        "class_declaration",
        "type_alias_declaration",
        "interface_declaration",
        "enum_declaration",
        "import_specifier",
        "import_clause",
        "namespace_import",
    },
    "java": {
        "method_declaration",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "variable_declarator",
        "import_declaration",
    },
    "csharp": {
        "method_declaration",
        "class_declaration",
        "struct_declaration",
        "interface_declaration",
        "enum_declaration",
        "variable_declarator",
        "using_directive",
        "using_alias_directive",
    },
    "go": {
        "function_declaration",
        "type_spec",
        "var_spec",
        "const_spec",
        "import_spec",
    },
    "rust": {
        "function_item",
        "struct_item",
        "enum_item",
        "type_item",
        "const_item",
        "static_item",
        "use_declaration",
    },
    "cpp": {
        "function_definition",
        "class_specifier",
        "struct_specifier",
        "type_definition",
        "alias_declaration",
        "using_declaration",
        "init_declarator",
        "namespace_alias_definition",
    },
}
SCOPE_NODES = {
    "function_declaration",
    "function_definition",
    "function_item",
    "method_declaration",
    "method_definition",
    "class_declaration",
    "class_specifier",
    "struct_item",
    "impl_item",
}
CLASS_NODES = {
    "class_declaration",
    "class_specifier",
    "struct_item",
    "struct_specifier",
}
IMPORT_NODE_TYPES = {
    "import_spec",
    "import_specifier",
    "import_clause",
    "namespace_import",
    "import_declaration",
    "using_directive",
    "using_alias_directive",
    "use_declaration",
}


def _walk(node):
    yield node
    for child in node.named_children:
        yield from _walk(child)


def unused_symbols(language: str, source: str, entry: str, parsed=None) -> list[str]:
    if language == "python":
        declared, identifiers = _python_symbols(source)
        counts = Counter(identifiers)
        recursive_functions = (
            node
            for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for node in recursive_functions:
            counts[node.name] -= _python_recursive_calls(node)
    else:
        parsed = parsed or parse_source(language, source)
        declared = _tree_declarations(language, parsed.root, parsed.source)
        identifiers = [
            n.text.decode()
            for n in _walk(parsed.root)
            if "identifier" in n.type and not n.named_children
        ]
        counts = Counter(identifiers)
    import_names = _import_names(language, source)
    import_counts = _import_reference_counts(language, source, import_names)
    for name in import_names:
        counts[name] = import_counts[name]
    declaration_counts = Counter(declared)
    return sorted(
        {
            name
            for name in declared
            if name != entry
            and name not in EXEMPT[language]
            and (
                counts.get(name, 0) == 0
                if name in import_names
                else counts.get(name, 0) <= declaration_counts[name]
            )
        }
    )


def _python_recursive_calls(node):
    return sum(
        isinstance(candidate, ast.Name)
        and candidate.id == node.name
        and isinstance(candidate.ctx, ast.Load)
        for candidate in ast.walk(node)
    )


def _import_names(language: str, source: str) -> set[str]:
    if language == "python":
        tree = ast.parse(source)
        return {
            alias.asname or alias.name.split(".")[0]
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
    parsed = parse_source(language, source)
    return {
        name
        for node in _walk(parsed.root)
        if node.type in IMPORT_NODE_TYPES
        if (name := _node_name(node, parsed.source))
    }


def _import_reference_counts(language: str, source: str, names: set[str]):
    if language == "python":
        tree = ast.parse(source)
        references = (
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        )
        return Counter(name for name in references if name in names)
    parsed = parse_source(language, source)
    import_spans = [
        (node.start_byte, node.end_byte)
        for node in _walk(parsed.root)
        if node.type in IMPORT_NODE_TYPES
        and not any(ancestor.type in IMPORT_NODE_TYPES for ancestor in _ancestors(node))
    ]
    references = (
        node.text.decode()
        for node in _walk(parsed.root)
        if "identifier" in node.type
        and not node.named_children
        and not any(start <= node.start_byte < end for start, end in import_spans)
    )
    return Counter(name for name in references if name in names)


def _ancestors(node):
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def _python_symbols(source: str) -> tuple[list[str], list[str]]:
    tree = ast.parse(source)
    declared = [
        name for statement in tree.body for name in _top_level_declarations(statement)
    ]
    identifiers = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    identifiers.extend(_top_level_callable_names(tree))
    identifiers.extend(_top_level_import_names(tree))
    return declared, identifiers


def _top_level_declarations(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [name for target in targets for name in _assigned_names(target)]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _imported_names(node)
    return []


def _assigned_names(target):
    return [node.id for node in ast.walk(target) if isinstance(node, ast.Name)]


def _top_level_callable_names(tree):
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def _top_level_import_names(tree):
    return [
        name
        for statement in tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
        for name in _imported_names(statement)
    ]


def _imported_names(node):
    return [alias.asname or alias.name.split(".")[0] for alias in node.names]


def _tree_declarations(language: str, root, data: bytes) -> list[str]:
    return [
        name
        for node in root.named_children
        for name in _declarations_in(node, language, data)
    ]


def _declarations_in(node, language: str, data: bytes) -> list[str]:
    if node.type in {"class_body", "declaration_list", "field_declaration_list"}:
        return _member_declarations(node, language, data)
    if node.type in CLASS_NODES:
        return _class_declarations(node, language, data)
    if node.type in SCOPE_NODES:
        name = _node_name(node, data)
        return [name] if name else []
    if node.type not in DECLARATION_KINDS[language]:
        return [
            name
            for child in node.named_children
            for name in _declarations_in(child, language, data)
        ]
    name = _node_name(node, data)
    if name:
        return [name]
    return [
        found
        for child in node.named_children
        for found in _declarations_in(child, language, data)
    ]


def _member_declarations(node, language: str, data: bytes) -> list[str]:
    declaration_types = DECLARATION_KINDS[language] | SCOPE_NODES
    return [
        name
        for child in node.named_children
        if child.type in declaration_types or child.type in CLASS_NODES
        for name in _declarations_in(child, language, data)
    ]


def _class_declarations(node, language: str, data: bytes) -> list[str]:
    name = _node_name(node, data)
    found = [name] if name else []
    children = [
        child
        for child in node.named_children
        if child.type not in {"field_declaration", "field_declaration_list"}
    ]
    return found + [
        value for child in children for value in _declarations_in(child, language, data)
    ]


def _node_name(node, data: bytes) -> str | None:
    if node.type == "function_definition":
        name = _tree_name(node, data)
        return name if name != "<anonymous>" else None
    name = node.child_by_field_name("name") or node.child_by_field_name("declarator")
    if name is not None:
        while (
            name.type
            not in {
                "identifier",
                "field_identifier",
                "type_identifier",
                "namespace_identifier",
            }
            and name.named_children
        ):
            name = name.child_by_field_name("name") or name.named_children[0]
        if "identifier" in name.type:
            return name.text.decode()
    if node.type in {
        "using_declaration",
        "use_declaration",
        "import_declaration",
        "import_spec",
        "import_specifier",
        "import_clause",
        "namespace_import",
        "using_directive",
        "using_alias_directive",
        "type_definition",
        "alias_declaration",
    }:
        words = re.findall(r"[A-Za-z_$][\w$]*", node.text.decode())
        if words:
            return words[-1]
    return None


def unused_python_locals(source: str) -> list[str]:
    tree = ast.parse(source)
    return sorted(
        {
            name
            for function in (
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            )
            for name in _unused_in_scope(function)
        }
    )


def _unused_in_scope(function) -> set[str]:
    collector = _LocalNames()
    collector.root = function
    collector.visit(function.body if isinstance(function, ast.Lambda) else function)
    return collector.assigned - collector.read - collector.non_f841 - {"_"}


def _closure_reads(function) -> set[str]:
    collector = _LocalNames()
    collector.root = function
    collector.visit(function)
    return collector.read - collector.assigned - _parameter_names(function)


def _parameter_names(function) -> set[str]:
    args = function.args
    return {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)} | {
        arg.arg for arg in (args.vararg, args.kwarg) if arg
    }


class _LocalNames(ast.NodeVisitor):
    def __init__(self):
        self.assigned: set[str] = set()
        self.read: set[str] = set()
        self.non_f841: set[str] = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.read.add(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.assigned.add(node.id)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                self.non_f841.update(
                    n.id for n in ast.walk(target) if isinstance(n, ast.Name)
                )
            self.visit(target)
        self.visit(node.value)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            self.read.add(node.target.id)
            self.assigned.add(node.target.id)
        self.visit(node.value)

    def visit_For(self, node):
        self.non_f841.update(
            n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)
        )
        self.visit(node.iter)
        for child in (*node.body, *node.orelse):
            self.visit(child)
        self.visit(node.target)

    visit_AsyncFor = visit_For

    def visit_FunctionDef(self, node):
        if node is getattr(self, "root", None):
            self.generic_visit(node)
            return
        self.assigned.add(node.name)
        self.read.update(_closure_reads(node))
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default:
                self.visit(default)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        if node is getattr(self, "root", None):
            self.generic_visit(node)
            return
        self.read.update(_closure_reads(node))

    def visit_ClassDef(self, node):
        self.assigned.add(node.name)
