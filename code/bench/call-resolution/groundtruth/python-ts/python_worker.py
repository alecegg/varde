"""Emit a deterministic class-stratified set of Python call sites."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import jedi

PER_REPO_CLASS_LIMIT = 50
EXCLUDED_PARTS = {"__pycache__", "test", "tests", "vendor", "vendored"}
DYNAMIC_NAMES = {"delattr", "eval", "exec", "getattr", "globals", "locals", "setattr"}


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    source_roots = json.loads(sys.argv[2])
    project = jedi.Project(path=str(root))
    candidates = []
    for source_root in source_roots:
        base = root / source_root
        for path in sorted(base.rglob("*.py")):
            if EXCLUDED_PARTS.intersection(part.lower() for part in path.parts):
                continue
            candidates.extend(_file_candidates(root, path))

    selected = _stratified_candidates(candidates)
    scripts: dict[Path, jedi.Script] = {}
    sites = [_resolve_site(root, item, project, scripts) for item in selected]
    json.dump(sites, sys.stdout, ensure_ascii=False)


def _file_candidates(root: Path, path: Path) -> list[dict[str, Any]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception as error:
        if isinstance(error, (OSError, UnicodeError, SyntaxError)):
            return []
        raise

    relative = path.relative_to(root).as_posix()
    imported = _imported_names(tree)
    declarations = _local_declarations(tree)
    assigned = _assigned_names(tree)
    candidates = []

    def visit(node: ast.AST, parents: tuple[tuple[str, int], ...]) -> None:
        active = parents
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            active = (*parents, (node.name, node.lineno))
        if isinstance(node, ast.Call):
            hint = _class_hint(node.func, declarations, imported, assigned)
            candidates.append(
                {
                    "path": path,
                    "relative": relative,
                    "call": node,
                    "parents": active,
                    "imported": imported,
                    "hint": hint,
                }
            )
        for child in ast.iter_child_nodes(node):
            visit(child, active)

    visit(tree, ())
    return candidates


def _class_hint(expression, declarations, imported, assigned):
    if isinstance(expression, ast.Call):
        hint = "higher_order"
    elif isinstance(expression, ast.Name):
        name = expression.id
        if name in DYNAMIC_NAMES:
            hint = "dynamic"
        elif name in assigned:
            hint = "higher_order"
        else:
            definitions = declarations.get(name, [])
            if len(definitions) == 1:
                hint = (
                    "constructor"
                    if isinstance(definitions[0], ast.ClassDef)
                    else "same_file"
                )
            elif name in imported:
                hint = "imported"
            elif not definitions:
                hint = "higher_order"
            else:
                hint = "dynamic"
    elif isinstance(expression, ast.Attribute):
        hint = "member"
    else:
        hint = "dynamic"
    return hint


def _stratified_candidates(candidates):
    by_class = defaultdict(list)
    for item in candidates:
        by_class[item["hint"]].append(item)
    selected = []
    for call_class in sorted(by_class):
        ordered = sorted(by_class[call_class], key=_candidate_key)
        selected.extend(ordered[:PER_REPO_CLASS_LIMIT])
    return sorted(
        selected,
        key=lambda item: (item["relative"], item["call"].lineno, item["hint"]),
    )


def _resolve_site(root, item, project, scripts):
    relative = item["relative"]
    call = item["call"]
    target = None
    external = False
    hint = item["hint"]
    path = item["path"]
    lookup = (
        "goto"
        if hint in {"same_file", "constructor", "imported"}
        and isinstance(call.func, ast.Name)
        else "infer"
    )
    try:
        script = scripts.get(path)
        if script is None:
            script = jedi.Script(path=str(path), project=project)
            scripts[path] = script
        if lookup == "goto":
            definitions = script.goto(
                line=call.func.lineno,
                column=_call_column(call.func),
                follow_imports=True,
                follow_builtin_imports=True,
            )
        else:
            definitions = script.infer(
                line=call.func.lineno,
                column=_call_column(call.func),
            )
        unique = {
            (
                str(definition.module_path),
                definition.line,
                definition.name,
                definition.type,
            ): definition
            for definition in definitions
        }
        resolution_error = False
    except Exception:  # noqa: BLE001 - a failed site stays unknown instead of aborting
        unique = {}
        resolution_error = True

    if resolution_error:
        resolution = "unknown-tool-error"
    elif len(unique) == 1:
        definition = next(iter(unique.values()))
        try:
            target = _target(root, definition)
            external = target is None
            resolution = "external" if external else "resolved"
        except Exception:  # noqa: BLE001 - keep the site with an error marker
            resolution = "unknown-tool-error"
    else:
        resolution = "ambiguous" if unique else "unknown"
    truth_source = (
        f"jedi-{jedi.__version__}-{lookup}:{resolution};"
        "python-ast-syntax-classification-v2"
    )

    return {
        "file": relative,
        "line": call.lineno,
        "call_name": _call_name(call.func),
        "call_class": hint,
        "target_id": target["id"] if target else None,
        "target_module": target["module"] if target else None,
        "external": external,
        "truth_source": truth_source,
        "function_id": _function_id(relative, item["parents"])
        if item["parents"]
        else None,
        "module": _module_name(relative),
    }


def _target(root: Path, definition: Any):
    target_name = definition.name or "<anonymous>"
    if definition.type == "class":
        initializers = [
            item for item in definition.defined_names() if item.name == "__init__"
        ]
        if len(initializers) == 1:
            definition = initializers[0]
            target_name = f"{target_name}.{definition.name}"
    target_path = definition.module_path
    if target_path is None:
        return None
    try:
        relative = Path(target_path).resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    return {
        "id": f"{relative}::{target_name}@{definition.line or 1}",
        "module": _module_name(relative),
        "file": relative,
        "type": definition.type,
    }


def _call_name(expression: ast.expr) -> str:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return expression.attr
    if isinstance(expression, ast.Call):
        return _call_name(expression.func)
    return ast.unparse(expression)


def _call_column(expression: ast.expr) -> int:
    if isinstance(expression, ast.Attribute):
        return expression.end_col_offset - len(expression.attr)
    return expression.col_offset


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _local_declarations(tree: ast.Module):
    declarations = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declarations[node.name].append(node)
    return declarations


def _assigned_names(tree: ast.Module) -> set[str]:
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            names.update(argument.arg for argument in node.args.args)
    return names


def _candidate_key(item):
    call = item["call"]
    identity = f"{item['relative']}:{call.lineno}:{call.col_offset}:{item['hint']}"
    return hashlib.sha256(identity.encode("utf-8")).digest()


def _module_name(relative: str) -> str:
    return Path(relative).with_suffix("").as_posix().replace("/", ".")


def _function_id(relative: str, parents: tuple[tuple[str, int], ...]) -> str:
    name = ".".join(item[0] for item in parents) or "<module>"
    return f"{relative}::{name}@{parents[-1][1]}"


if __name__ == "__main__":
    main()
