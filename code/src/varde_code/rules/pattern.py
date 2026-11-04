"""Pattern-rule execution and conversion of ast-grep matches to findings."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from ast_grep_py import SgRoot

from varde_code import ApiError, pattern_match
from varde_code.git import run_git
from varde_code.model import Span
from varde_code.parse import SUPPORTED_LANGUAGES, language_for_path, parse_source
from varde_code.rules.correlate import EnclosingLookup, TestPathLookup
from varde_code.rules.finding import FileState, Finding, Location, match_to_finding
from varde_code.rules.model import ConstraintSpec, Diagnostic, Rule, RuleKind
from varde_code.rules.rewrite import template_tokens


def apply_constraints(
    matches: list[dict[str, Any]], constraints: dict[str, ConstraintSpec]
) -> list[dict[str, Any]]:
    """Filter matches using ANDed regular expressions for each capture."""
    compiled: list[tuple[str, bool, re.Pattern[str]]] = []
    for name, spec in constraints.items():
        if not spec.patterns:
            raise ApiError(
                "invalid_constraint",
                f"constraint list for capture `{name}` must not be empty",
            )
        for source in spec.patterns:
            negate = source.startswith("!")
            if negate:
                source = source[1:]  # noqa: PLW2901 - strip the negation prefix
            try:
                compiled.append((name, negate, re.compile(_python_regex(source))))
            except re.error as error:
                raise ApiError(
                    "invalid_constraint",
                    f"constraint for capture `{name}` is not a valid regex: {error}",
                ) from error
    if not compiled:
        return list(matches)

    kept = []
    for match in matches:
        captures = match.get("captures")
        if not isinstance(captures, dict):
            continue
        for name, negate, regex in compiled:
            capture = captures.get(name)
            if isinstance(capture, list):
                text = "".join(
                    node["text"]
                    for node in capture
                    if isinstance(node, dict) and isinstance(node.get("text"), str)
                )
            elif isinstance(capture, dict) and isinstance(capture.get("text"), str):
                text = capture["text"]
            else:
                break
            if bool(regex.search(text)) == negate:
                break
        else:
            kept.append(match)
    return kept


def _python_regex(source: str) -> str:
    """Translate the Rust regex syntax used by rules to Python ``re`` syntax."""
    if re.search(r"\(\?(?:[=!]|<[=!])", source):
        raise re.error("look-around is not supported by Rust regex")
    if re.search(r"\\(?:[1-9]|k<|g<)", source):
        raise re.error("backreferences are not supported by Rust regex")

    def sequence(index: int, nested: bool) -> tuple[str, int]:
        output: list[str] = []
        while index < len(source):
            char = source[index]
            if char == "\\":
                output.append(source[index : index + 2])
                index += 2
                continue
            if char == "[":
                end = index + 1
                while end < len(source):
                    if source[end] == "\\":
                        end += 2
                    elif source[end] == "]":
                        end += 1
                        break
                    else:
                        end += 1
                output.append(source[index:end])
                index = end
                continue
            if char == ")" and nested:
                return "".join(output), index
            if source.startswith("(?", index):
                flags = re.match(r"\(\?([imsxUu-]+)\)", source[index:])
                if flags:
                    rust_flags = flags.group(1)
                    if "U" in rust_flags:
                        raise re.error(
                            "Rust ungreedy flag `U` is unsupported by Python re"
                        )
                    py_flags = rust_flags.replace("u", "")
                    tail, end = sequence(index + len(flags.group()), nested)
                    output.append(f"(?{py_flags}:{tail})")
                    index = end
                    continue
            if char == "(":
                prefix_end = index + 1
                if source.startswith("(?:", index):
                    prefix_end = index + 3
                elif source.startswith("(?P<", index):
                    name_end = source.find(">", index + 4)
                    if name_end != -1:
                        prefix_end = name_end + 1
                inner, end = sequence(prefix_end, True)
                output.append(source[index:prefix_end] + inner)
                if end < len(source) and source[end] == ")":
                    output.append(")")
                    index = end + 1
                else:
                    index = end
                continue
            output.append(char)
            index += 1
        return "".join(output), index

    translated, _ = sequence(0, False)
    return translated


def capture_names(template: str) -> list[str]:
    """Return distinct capture names in the order they occur."""
    names: list[str] = []
    seen: set[str] = set()
    for token in template_tokens(template):
        if token.name not in seen:
            seen.add(token.name)
            names.append(token.name)
    return names


def validate_rewrite_template(rewrite: str, pattern: str) -> None:
    """Reject rewrites that reference captures absent from their pattern."""
    declared = set(capture_names(pattern))
    for name in capture_names(rewrite):
        if name not in declared:
            raise ValueError(
                f"rewrite references capture `{name}` which is not declared in pattern"
            )


def run_pattern_rules(
    rules: list[Rule], repo_root: str | Path, conn: sqlite3.Connection
) -> tuple[list[Finding], list[Diagnostic]]:
    """Run pattern rules, retaining per-rule diagnostics and enrichment data."""
    root = Path(repo_root)
    try:
        conn.execute(
            "SELECT f.id, f.path, f.is_test_path, f.is_tooling_path "
            "FROM files f LIMIT 0"
        )
        conn.execute(
            "SELECT e.kind, e.name, e.is_async, e.start_byte, e.end_byte "
            "FROM entities e JOIN files f ON f.id=e.file_id LIMIT 0"
        )
    except sqlite3.Error as error:
        raise ApiError("db_error", str(error)) from error

    enclosing = EnclosingLookup(conn)
    test_paths = TestPathLookup(conn)
    file_states: dict[str, FileState | None] = {}
    findings: list[Finding] = []
    diagnostics: list[Diagnostic] = []
    for rule in rules:
        if rule.kind != RuleKind.PATTERN:
            continue
        if rule.pattern is None:
            diagnostics.append(
                _diagnostic(
                    rule, root, "rule kind=pattern is missing its `pattern` field"
                )
            )
            continue
        try:
            apply_constraints([], rule.constraints or {})
        except ApiError as error:
            diagnostics.append(_diagnostic(rule, root, error.message))
            continue

        explicitly_scoped = bool(rule.languages)
        requested = rule.languages if explicitly_scoped else list(SUPPORTED_LANGUAGES)
        languages: list[str] = []
        for name in requested or []:
            try:
                language = pattern_match.language_name(name)
            except ValueError:
                diagnostics.append(
                    _diagnostic(
                        rule, root, f"unsupported language `{name}` in rule.languages"
                    )
                )
                continue
            if language not in languages:
                languages.append(language)

        pattern_matches: list[dict[str, Any]] = []
        parse_failures = 0
        files = _walk_pattern_files(root)
        for language in languages:
            if _has_pattern_error(rule.pattern, language):
                parse_failures += 1
                continue
            for file in files:
                if language_for_path(file) != language:
                    continue
                try:
                    source = Path(file).read_text(encoding="utf-8")
                except OSError, UnicodeError:
                    continue
                pattern_matches.extend(
                    _match_source(source, rule.pattern, language, file)
                )
        pattern_matches.sort(
            key=lambda row: (
                str(row.get("file", "")),
                int(row.get("span", {}).get("start_byte", 0)),
            )
        )

        if explicitly_scoped and parse_failures:
            diagnostics.append(
                _diagnostic(
                    rule,
                    root,
                    f"pattern failed to parse in {parse_failures} explicitly targeted "
                    "language(s)",
                )
            )
        elif not explicitly_scoped and languages and parse_failures == len(languages):
            diagnostics.append(
                _diagnostic(rule, root, "pattern does not parse in any target language")
            )
        try:
            selected = apply_constraints(pattern_matches, rule.constraints or {})
        except ApiError as error:
            diagnostics.append(_diagnostic(rule, root, error.message))
            continue

        for match in selected:
            file = match.get("file")
            if not isinstance(file, str):
                continue
            if rule.exclude_test_paths and test_paths.is_test_path(file):
                continue
            if rule.exclude_tooling_paths and test_paths.is_tooling_path(file):
                continue
            location = _location(file, match)
            if location is None:
                continue
            finding = match_to_finding(rule, match, location)
            real_path = str(Path(file).resolve())
            if real_path not in file_states:
                file_states[real_path] = FileState.of(real_path)
            finding.matched_file_state = file_states[real_path]
            try:
                fact = enclosing.lookup(
                    file, location.span.start_byte, location.span.end_byte
                )
            except sqlite3.Error as error:
                raise ApiError("db_error", str(error)) from error
            if fact is not None and isinstance(finding.evidence, dict):
                finding.evidence["enclosing_function"] = {
                    "name": fact.name,
                    "is_async": fact.is_async,
                }
            findings.append(finding)
    return findings, diagnostics


def _has_pattern_error(pattern: str, language: str) -> bool:
    """Validate pattern syntax after replacing metavariables with identifiers."""
    lang = pattern_match.language_name(language)
    source = re.sub(r"\$\$\$MOD\s+", "", pattern)
    source = re.sub(r"(?:\$\$\$|\$)[A-Za-z0-9_]+", "__VARDE_META__", source)
    if lang == "python":
        lines = source.splitlines()
        source = lines[0] + "".join(f"\n    {line}" for line in lines[1:])
    elif lang == "csharp" and "{" in source and "get;" in source:
        source = f"class __VardeWrapper__ {{ {source} }}"
    elif lang == "solidity" and source.lstrip().startswith("catch "):
        source = (
            f"contract __VardeWrapper__ {{ function __varde_wrapper__() public "
            f"{{ try __varde_call__() {{ }} {source} }} }}"
        )
    elif lang == "solidity" and source.lstrip().startswith("string constant "):
        source = f"contract __VardeWrapper__ {{ {source} }}"
    else:
        source = pattern_match.wrap_pattern(language, source)
    root = SgRoot(source, lang).root()
    pending = [root]
    while pending:
        node = pending.pop()
        if node.kind() == "ERROR":
            return True
        pending.extend(node.children())
    return False


def _walk_pattern_files(root: Path) -> list[str]:
    """Return sorted tracked and non-ignored files, including dotfiles."""
    listed = run_git(
        ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], root
    )
    if listed is not None:
        return sorted(
            str(root / relative) for relative in listed.split("\0") if relative
        )

    files: list[str] = []
    for current, directories, names in os.walk(root):
        directories[:] = sorted(name for name in directories if name != ".git")
        files.extend(str(Path(current) / name) for name in names)
    return sorted(files)


def _match_source(
    source: str, pattern: str, language: str, file: str | None = None
) -> list[dict[str, Any]]:
    """Match one source and attach the shared capture shape used by rule tests."""
    root = SgRoot(source, pattern_match.language_name(language))
    try:
        tree_root = parse_source(language, source).root
    except RuntimeError, ValueError:
        tree_root = None
    if (
        pattern == "$$$MOD $TYPE $KEY = $VAL"
        and pattern_match.language_name(language) == "java"
    ):
        return (
            _match_java_field_pattern(tree_root, file) if tree_root is not None else []
        )
    rows: list[dict[str, Any]] = []
    try:
        matched_nodes = list(root.root().find_all({"rule": {"pattern": pattern}}))
    except RuntimeError as error:
        if "Multiple AST nodes are detected" not in str(error):
            raise
        if pattern.startswith("$$$MOD "):
            try:
                matched_nodes = list(
                    root.root().find_all(
                        {"rule": {"pattern": pattern.removeprefix("$$$MOD ")}}
                    )
                )
            except RuntimeError as inner_error:
                if "Multiple AST nodes are detected" not in str(inner_error):
                    raise
                if (
                    pattern_match.language_name(language) == "csharp"
                    and "{ get;" in pattern
                    and tree_root is not None
                ):
                    return _match_csharp_property_pattern(tree_root, pattern, file)
                return []
        elif tree_root is not None:
            return _match_empty_catch_pattern(
                tree_root, source, pattern, language, file
            )
        else:
            return []
    if not matched_nodes and pattern.startswith("$$$MOD "):
        stripped = pattern.removeprefix("$$$MOD ")
        matched_nodes = list(root.root().find_all({"rule": {"pattern": stripped}}))
    for node in matched_nodes:
        text = node.text()
        if (
            pattern.startswith("_ = ")
            and pattern_match.language_name(language) == "go"
            and re.match(r"\s*_,\s*_\s*=", text)
        ):
            continue
        if _empty_handler_comment(pattern, text, language):
            continue
        rng = node.range()
        captures: dict[str, Any] = {}
        for name in capture_names(pattern):
            bound = node.get_match(name)
            if bound is not None:
                captures[name] = _node_data(bound, tree_root, language)
                continue
            multiple = node.get_multiple_matches(name)
            if multiple:
                captures[name] = [
                    _node_data(item, tree_root, language)
                    for item in multiple
                    if item.is_named()
                ]
            elif name == "ARGS" and re.search(r"\$\$\$ARGS\b", pattern):
                captures[name] = []
        row = {
            "kind": _tree_sitter_kind(tree_root, rng.start.index, rng.end.index)
            or node.kind(),
            "text": text,
            "range": rng,
            "captures": captures,
            "span": _span_data(rng),
        }
        if file is not None:
            row["file"] = file
        rows.append(row)
    if (
        not rows
        and pattern == "$CMD $$$ARGS || $NOOP"
        and pattern_match.language_name(language) == "bash"
        and tree_root is not None
    ):
        rows.extend(_match_bash_ignored_status(tree_root, language, file))
    return rows


def _match_java_field_pattern(tree_root: Any, file: str | None) -> list[dict[str, Any]]:
    rows = []
    pending = [tree_root]
    while pending:
        node = pending.pop()
        pending.extend(reversed(node.children))
        if node.type != "field_declaration":
            continue
        type_node = node.child_by_field_name("type")
        declarator = node.child_by_field_name("declarator")
        key = declarator.child_by_field_name("name") if declarator is not None else None
        value = (
            declarator.child_by_field_name("value") if declarator is not None else None
        )
        if type_node is None or key is None or value is None:
            continue
        captures = {
            "TYPE": _tree_node_data(type_node, "java"),
            "KEY": _tree_node_data(key, "java"),
            "VAL": _tree_node_data(value, "java"),
        }
        rows.append(_tree_match_row(node, captures, file))
    return rows


def _match_csharp_property_pattern(
    tree_root: Any, pattern: str, file: str | None
) -> list[dict[str, Any]]:
    accessor_text = "{ get; init; }" if "{ get; init; }" in pattern else "{ get; }"
    rows = []
    pending = [tree_root]
    while pending:
        node = pending.pop()
        pending.extend(reversed(node.children))
        if node.type != "property_declaration":
            continue
        type_node = node.child_by_field_name("type")
        key = node.child_by_field_name("name")
        accessors = node.child_by_field_name("accessors")
        value = node.child_by_field_name("value")
        if type_node is None or key is None or value is None or accessors is None:
            continue
        if accessors.text.decode("utf-8") != accessor_text:
            continue
        captures = {
            "TYPE": _tree_node_data(type_node, "csharp"),
            "KEY": _tree_node_data(key, "csharp"),
            "VAL": _tree_node_data(value, "csharp"),
        }
        rows.append(_tree_match_row(node, captures, file))
    return rows


def _match_bash_ignored_status(
    tree_root: Any, language: str, file: str | None
) -> list[dict[str, Any]]:
    rows = []
    pending = [tree_root]
    while pending:
        node = pending.pop()
        pending.extend(reversed(node.children))
        if node.type != "list":
            continue
        children = node.children
        for index, operator in enumerate(children):
            if operator.type != "||" or index == 0 or index + 1 == len(children):
                continue
            command = children[index - 1]
            noop = children[index + 1]
            if command.type != "command" or noop.type != "command":
                continue
            noop_name = noop.child_by_field_name("name")
            if noop_name is None or noop_name.text.decode("utf-8") not in {"true", ":"}:
                continue
            command_name = command.child_by_field_name("name")
            if command_name is None or not command_name.named_children:
                continue
            arguments = [
                child
                for child in command.named_children
                if child.type != "command_name"
            ]
            captures = {
                "CMD": _tree_node_data(command_name.named_children[0], language),
                "ARGS": [_tree_node_data(child, language) for child in arguments],
                "NOOP": _tree_node_data(noop_name.named_children[0], language)
                if noop_name.named_children
                else _tree_node_data(noop_name, language),
            }
            rows.append(_tree_match_row(node, captures, file))
    return rows


def _match_empty_catch_pattern(
    tree_root: Any, source: str, pattern: str, language: str, file: str | None
) -> list[dict[str, Any]]:
    """Match catch patterns that ast-grep-py rejects as multiple root nodes."""
    lang = pattern_match.language_name(language)
    if "catch" not in pattern:
        return []
    rows = []
    pending = [tree_root]
    while pending:
        node = pending.pop()
        pending.extend(reversed(node.children))
        if node.type == "catch_clause" and lang in {"csharp", "php"}:
            body = node.child_by_field_name("body")
            if (
                body is None
                or body.named_children
                or "//" in body.text.decode()
                or "/*" in body.text.decode()
            ):
                continue
            captures = {}
            for key, field in (("TYPE", "type"), ("ERR", "name")):
                captured = node.child_by_field_name(field)
                if captured is None:
                    declaration = next(
                        (
                            child
                            for child in node.named_children
                            if child.type == "catch_declaration"
                        ),
                        None,
                    )
                    captured = (
                        declaration.child_by_field_name(field)
                        if declaration is not None
                        else None
                    )
                if captured is not None:
                    captures[key] = _tree_node_data(captured, language)
            rows.append(_tree_match_row(node, captures, file))
        elif (
            node.type == "try_statement"
            and lang == "dart"
            and "$$$A" in pattern
            and " on " not in pattern
        ):
            catch = next(
                (
                    child
                    for child in node.named_children
                    if child.type == "catch_clause"
                ),
                None,
            )
            blocks = [child for child in node.named_children if child.type == "block"]
            if catch is None or len(blocks) < 2:
                continue
            body = blocks[0]
            catch_body = blocks[-1]
            if (
                catch_body.named_children
                or "//" in catch_body.text.decode()
                or "/*" in catch_body.text.decode()
            ):
                continue
            exception = next(
                (
                    child
                    for child in catch.named_children
                    if child.type == "catch_parameters"
                ),
                None,
            )
            err = (
                exception.named_children[-1]
                if exception and exception.named_children
                else None
            )
            statements = []
            for child in body.named_children:
                if child.type == "expression_statement" and child.named_children:
                    children = child.named_children
                    if len(children) > 1 and children[-1].type == "selector":
                        end = child.end_byte - (1 if child.text.endswith(b";") else 0)
                        expression = (
                            source.encode("utf-8")[child.start_byte : end]
                            .decode("utf-8")
                            .strip()
                        )
                        _end_row, end_col = child.end_point
                        statements.append(
                            {
                                "kind": "call_expression",
                                "text": expression,
                                "span": _tree_span_data_between(
                                    child.start_byte,
                                    end,
                                    child.start_point,
                                    child.end_point,
                                    end_col - (1 if end < child.end_byte else 0),
                                ),
                            }
                        )
                        continue
                    child = children[0]  # noqa: PLW2901 - unwrap single-child statements
                statements.append(_tree_node_data(child, language))
            captures: dict[str, Any] = {"A": statements}
            if err is not None:
                captures["ERR"] = _tree_node_data(err, language)
            rows.append(_tree_match_row(node, captures, file))
    return rows


def _tree_match_row(
    node: Any, captures: dict[str, Any], file: str | None
) -> dict[str, Any]:
    row = {
        "kind": node.type,
        "text": node.text.decode("utf-8"),
        "span": _tree_span_data(node),
        "captures": captures,
    }
    if file is not None:
        row["file"] = file
    return row


def _tree_node_data(node: Any, language: str) -> dict[str, Any]:
    kind = node.type
    text = node.text.decode("utf-8")
    if pattern_match.language_name(language) == "php" and kind == "variable_name":
        kind, text = "name", text.removeprefix("$")
    return {"kind": kind, "text": text, "span": _tree_span_data(node)}


def _tree_span_data(node: Any) -> dict[str, int]:
    start_row, start_col = node.start_point
    end_row, end_col = node.end_point
    return {
        "start_byte": node.start_byte,
        "end_byte": node.end_byte,
        "start_line": start_row + 1,
        "start_col": start_col,
        "end_line": end_row + 1,
        "end_col": end_col,
    }


def _tree_span_data_between(
    start: int, end: int, start_point: Any, end_point: Any, end_col: int
) -> dict[str, int]:
    start_row, start_col = start_point
    end_row, _ = end_point
    return {
        "start_byte": start,
        "end_byte": end,
        "start_line": start_row + 1,
        "start_col": start_col,
        "end_line": end_row + 1,
        "end_col": end_col,
    }


def _empty_handler_comment(pattern: str, text: str, language: str) -> bool:
    """Keep comment-only handler bodies from matching empty-handler rules."""
    empty_catch = "catch" in pattern and re.search(r"\{\s*\}\s*$", pattern)
    empty_except = "except" in pattern and pattern.rstrip().endswith("pass")
    if not (empty_catch or empty_except):
        return False
    if empty_catch:
        catch = text.find("catch")
        opening = text.find("{", catch)
        closing = text.rfind("}")
        body = (
            text[opening + 1 : closing] if opening != -1 and closing > opening else ""
        )
    else:
        except_clause = text.find("except")
        colon = text.find(":", except_clause)
        body = text[colon + 1 :] if colon != -1 else ""
    lang = pattern_match.language_name(language)
    if lang == "python" or lang in {"bash", "ruby"}:
        return "#" in body
    if lang in {
        "typescript",
        "tsx",
        "javascript",
        "c",
        "cpp",
        "go",
        "java",
        "csharp",
        "kotlin",
        "swift",
        "dart",
        "solidity",
    }:
        return "//" in body or "/*" in body
    return False


def _node_data(node: Any, tree_root: Any, language: str) -> dict[str, Any]:
    rng = node.range()
    tree_node = _tree_sitter_node(tree_root, rng.start.index, rng.end.index)
    kind = tree_node.type if tree_node is not None else node.kind()
    text = node.text()
    if tree_node is not None:
        text = tree_node.text.decode("utf-8")
        if (
            tree_node.type == "expression_statement"
            and len(tree_node.named_children) == 1
        ):
            tree_node = tree_node.named_children[0]
            kind = tree_node.type
            text = tree_node.text.decode("utf-8")
    if pattern_match.language_name(language) == "php" and kind == "variable_name":
        kind = "name"
        text = text.removeprefix("$")
    return {"kind": kind, "text": text, "span": _span_data(rng)}


def _tree_sitter_kind(root: Any | None, start: int, end: int) -> str | None:
    """Find the deepest source node matching an ast-grep byte span."""
    node = _tree_sitter_node(root, start, end)
    return node.type if node is not None else None


def _tree_sitter_node(root: Any | None, start: int, end: int) -> Any | None:
    """Find the deepest source node matching an ast-grep byte span."""
    if root is None:
        return None
    for child in root.children:
        if child.start_byte > start or child.end_byte < end:
            continue
        node = _tree_sitter_node(child, start, end)
        if node is not None:
            return node
    if root.start_byte == start and root.end_byte == end:
        return root
    return None


def _span_data(rng: Any) -> dict[str, int]:
    return {
        "start_byte": rng.start.index,
        "end_byte": rng.end.index,
        "start_line": rng.start.line + 1,
        "start_col": rng.start.column,
        "end_line": rng.end.line + 1,
        "end_col": rng.end.column,
    }


def _location(file: str, match: dict[str, Any]) -> Location | None:
    span = match.get("span")
    if not isinstance(span, dict):
        return None
    return Location(
        file,
        Span(
            *(
                int(span[key])
                for key in (
                    "start_byte",
                    "end_byte",
                    "start_line",
                    "start_col",
                    "end_line",
                    "end_col",
                )
            )
        ),
    )


def _diagnostic(rule: Rule, root: Path, reason: str) -> Diagnostic:
    return Diagnostic(rule.id, str(root), reason)
