"""Entry documentation and declaration-form extraction."""

from __future__ import annotations

import ast
import re

from item_spec_extract import _tree_name
from item_spec_symbols import _walk
from varde_code.parse import parse_source

DECLARATION_FORMS = {
    "typescript": {
        "function_declaration": "function declaration",
        "arrow_function": "arrow-const",
        "function_expression": "function-expression-const",
        "method_definition": "method",
    },
    "java": {"method_declaration": "method"},
    "csharp": {"method_declaration": "method"},
    "go": {"function_declaration": "function declaration", "func_literal": "lambda"},
    "rust": {"function_item": "function declaration", "closure_expression": "lambda"},
    "cpp": {
        "function_definition": "function declaration",
        "lambda_expression": "lambda",
    },
}
FUNCTION_NODES = {
    "arrow_function",
    "function_expression",
    "lambda_expression",
    "closure_expression",
    "func_literal",
}
COMMENT_TYPES = {"comment", "line_comment", "block_comment", "doc_comment"}


def entry_form(language: str, source: str, entry: str, parsed=None) -> str:
    if language == "python":
        return _python_entry_form(source, entry)
    parsed = parsed or parse_source(language, source)
    for node in _walk(parsed.root):
        form = _form_for_node(language, node, parsed.source, entry)
        if form:
            return form
    return "missing"


def _python_entry_form(source: str, entry: str) -> str:
    for node in ast.parse(source).body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == entry
        ):
            return "function declaration"
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _target(node) == entry:
            return (
                "lambda-const" if isinstance(node.value, ast.Lambda) else "assignment"
            )
    return "missing"


def _form_for_node(language: str, node, data: bytes, entry: str) -> str:
    if language == "typescript" and node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is not None and name.text.decode() == entry and value is not None:
            return {
                "arrow_function": "arrow-const",
                "function_expression": "function-expression-const",
            }.get(value.type, "assignment")
    if node.type in FUNCTION_NODES and _tree_name(node, data) == entry:
        return (
            "lambda"
            if language != "typescript" or node.type == "lambda_expression"
            else "missing"
        )
    if (
        language == "cpp"
        and node.type == "function_definition"
        and entry in _identifiers(node)
    ):
        return "function declaration"
    name = node.child_by_field_name("name")
    if name is not None and name.text.decode() == entry:
        return DECLARATION_FORMS.get(language, {}).get(node.type, "")
    return ""


def _identifiers(node) -> set[str]:
    return {
        n.text.decode()
        for n in _walk(node)
        if "identifier" in n.type and not n.named_children
    }


def _target(node) -> str | None:
    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
    return target.id if isinstance(target, ast.Name) else None


def entry_doc(language: str, source: str, entry: str, parsed=None) -> str:
    if language == "python":
        return _python_entry_doc(source, entry)
    parsed = parsed or parse_source(language, source)
    for node in _walk(parsed.root):
        if _declaration_has_entry(node, language, parsed.source, entry):
            return _attached_doc(node, source, language)
    return ""


def _python_entry_doc(source: str, entry: str) -> str:
    for node in ast.parse(source).body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == entry
        ):
            return _normalize(ast.get_docstring(node) or "")
    return ""


def _declaration_has_entry(node, language: str, data: bytes, entry: str) -> bool:
    declaration_types = set(DECLARATION_FORMS.get(language, {})) | {
        "function_definition",
        "lexical_declaration",
        "variable_declarator",
    }
    if node.type not in declaration_types:
        return False
    return entry in _identifiers(node)


def _attached_doc(node, source: str, language: str) -> str:
    statement = _doc_statement(node)
    start = statement.start_byte
    prior = _prior_comments(_source_root(statement), start)
    if not prior:
        return ""
    comments = _adjacent_comments(prior, source.encode(), start, language)
    return _normalize("\n".join(n.text.decode() for n in comments))


def _doc_statement(node):
    declaration_nodes = {
        "method_declaration",
        "method_definition",
        "function_declaration",
        "function_item",
        "function_definition",
    }
    statement = node
    while statement.parent is not None and statement.parent.type not in {
        "program",
        "source_file",
        "translation_unit",
        "compilation_unit",
    }:
        if statement.parent.type in {"export_statement", "export_declaration"}:
            return statement.parent
        if statement.type in declaration_nodes:
            return statement
        statement = statement.parent
    return statement


def _source_root(node):
    root = node
    while root.parent is not None and root.type not in {
        "program",
        "source_file",
        "translation_unit",
        "compilation_unit",
    }:
        root = root.parent
    return root


def _prior_comments(root, start: int):
    return [
        node
        for node in _walk(root)
        if node.type in COMMENT_TYPES
        and not _has_comment_ancestor(node)
        and node.end_byte <= start
    ]


def _has_comment_ancestor(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in COMMENT_TYPES:
            return True
        parent = parent.parent
    return False


def _adjacent_comments(prior, data: bytes, declaration_start: int, language: str):
    comments = []
    cursor = declaration_start
    for node in reversed(prior):
        gap = data[node.end_byte : cursor].decode()
        if not _allowed_gap(gap, language):
            break
        comments.append(node)
        cursor = node.start_byte
    return list(reversed(comments))


def _allowed_gap(gap: str, language: str) -> bool:
    if re.search(r"\n\s*\n", gap):
        return False
    prelude = re.sub(
        r"(?m)^\s*(?:export\s+|default\s+|@[A-Za-z_$][\w$]*(?:\([^\n]*\))?\s*|#\[[^\]]*\]\s*|\[\[[^\]]*\]\]\s*)",
        "",
        gap,
    )
    return not prelude.strip()


def _normalize(text: str) -> str:
    text = text.replace("/**", "").replace("*/", "")
    lines = [
        re.sub(r"^\s*(?:///|//|#|\*|<!--|-->|\*!)\s?", "", line)
        for line in text.splitlines()
    ]
    return " ".join(" ".join(lines).split())
