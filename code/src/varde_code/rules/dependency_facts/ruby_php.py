"""Ruby and PHP require-family dependency facts."""

from __future__ import annotations

from pathlib import Path

from ...parse import language_for_path, parse_source
from .types import (
    Fact,
    FactInput,
    FileRow,
    ImportRow,
    certified_fact,
    indexed_paths,
    missing_fact,
    physical_targets,
    resolve_relative_path,
)

RUBY_REQUIRE_FUNCTIONS = {"require", "require_relative", "load", "autoload"}
PHP_REQUIRE_KINDS = {
    "require_expression",
    "require_once_expression",
    "include_expression",
    "include_once_expression",
}


class Require:
    def __init__(
        self, spec: str, certifiable: bool, missing_eligible: bool, ruby: bool
    ):
        self.spec = spec
        self.certifiable = certifiable
        self.missing_eligible = missing_eligible
        self.ruby = ruby


def facts(input: FactInput) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    indexed = indexed_paths(input.files)
    imports_by_file: dict[int, list[ImportRow]] = {}
    for imp in input.imports:
        imports_by_file.setdefault(imp.file_id, []).append(imp)
    output: list[Fact] = []
    for source in input.files:
        language = language_for_path(source.path)
        if source.is_test or source.is_tooling or language not in {"ruby", "php"}:
            continue
        imports = imports_by_file.get(source.id)
        if not imports:
            continue
        try:
            text = source.physical.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        requires = ruby_requires(text) if language == "ruby" else php_requires(text)
        root = repository_root(source)
        next_index = 0
        for require in requires:
            offset = next(
                (
                    i
                    for i, imp in enumerate(imports[next_index:])
                    if imp.specifier == require.spec
                ),
                None,
            )
            if offset is None:
                continue
            next_index += offset
            imp = imports[next_index]
            next_index += 1
            if imp.type_only or not require.certifiable:
                continue
            fact = require_fact(root, by_id, indexed, source, imp, require)
            if fact is not None:
                output.append(fact)
    return output


def repository_root(source: FileRow) -> Path:
    root = source.physical
    for _ in Path(source.relative).parts:
        root = root.parent
    return root


def candidate_paths(base: str, require: Require) -> list[str]:
    if not require.ruby:
        return [base]
    extension = Path(base).suffix.removeprefix(".")
    if extension.lower() == "rb":
        return [base]
    if extension:
        return [base, base + ".rb"]
    return [base + ".rb"]


def require_fact(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    source: FileRow,
    imp: ImportRow,
    require: Require,
) -> Fact | None:
    base = resolve_relative_path(source.relative, require.spec)
    if base is None:
        return None
    targets = physical_targets(root, candidate_paths(base, require))
    indexed_ids = [
        file_id for path, _ in targets.paths for file_id in indexed.get(path, [])
    ]
    if len(targets.paths) == 1 and len(indexed_ids) == 1:
        return certified_fact(by_id, source, imp, indexed_ids[0])
    if not targets.paths and not targets.existing_path and require.missing_eligible:
        return missing_fact(source, imp)
    return None


def ruby_requires(text: str) -> list[Require]:
    root = parse_source("ruby", text).root
    output: list[Require] = []
    for node in walk(root):
        if node.type != "call":
            continue
        method = node.child_by_field_name("method")
        if method is None:
            continue
        method_text = method.text
        if method_text is None:
            continue
        method_name = method_text.decode()
        if method_name not in RUBY_REQUIRE_FUNCTIONS:
            continue
        argument = next(
            (child for child in node.children if child.type == "argument_list"), None
        )
        if argument is None:
            continue
        arg = next(
            (child for child in argument.children if child.type not in {"(", ",", ")"}),
            None,
        )
        if arg is None or arg.type != "string":
            continue
        spec = join_string_content(arg)
        if not spec:
            continue
        guarded = any(
            parent.type == "rescue_modifier"
            or any(child.type == "rescue" for child in parent.children)
            for parent in ancestors(node)
        )
        dynamic = has_kind(arg, "interpolation")
        certifiable = method_name == "require_relative" and not guarded and not dynamic
        output.append(Require(spec, certifiable, certifiable, True))
    return output


def php_requires(text: str) -> list[Require]:
    root = parse_source("php", text).root
    output: list[Require] = []
    for node in walk(root):
        if node.type not in PHP_REQUIRE_KINDS:
            continue
        arg = next(
            (
                child
                for child in node.children
                if child.type in {"string", "encapsed_string"}
            ),
            None,
        )
        if arg is None:
            continue
        spec = normalize_namespace(join_string_content(arg))
        if not spec:
            continue
        guarded = any(
            parent.type == "error_suppression_expression" for parent in ancestors(node)
        )
        dynamic = any(
            child.type
            in {
                "variable_name",
                "dynamic_variable_name",
                "member_access_expression",
                "subscript_expression",
                "function_call_expression",
            }
            for child in arg.children
        )
        certifiable = not guarded and not dynamic
        output.append(
            Require(
                spec, certifiable, certifiable and is_explicitly_relative(spec), False
            )
        )
    return output


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def ancestors(node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def has_kind(node, kind: str) -> bool:
    return any(child.type == kind for child in node.children)


def join_string_content(node) -> str:
    return "".join(
        child.text.decode("utf-8", errors="replace")
        for child in node.children
        if child.type == "string_content"
    )


def normalize_namespace(spec: str) -> str:
    return spec.lstrip("\\").replace("\\", "/")


def is_explicitly_relative(spec: str) -> bool:
    return spec.startswith(("./", "../"))
