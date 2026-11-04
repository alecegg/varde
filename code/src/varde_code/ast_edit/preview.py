"""Build deterministic, content-addressed AST rewrite proposals."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Never

from ast_grep_py import SgRoot

from varde_code.pattern_match import language_name
from varde_code.rules.pattern import validate_rewrite_template
from varde_code.rules.rewrite import substitute_with_source


@dataclass(frozen=True)
class RewriteRule:
    id: str
    language: str
    pattern: str
    replacement: str
    inside: dict[str, str] | None = None
    has: dict[str, str] | None = None
    precedes: dict[str, str] | None = None
    follows: dict[str, str] | None = None


@dataclass
class Diagnostic:
    code: str
    message: str
    blocking: bool
    path: str | None = None
    rule_ids: list[str] | None = None
    start_byte: int | None = None
    end_byte: int | None = None


@dataclass
class PreviewResult:
    complete: bool
    applicable: bool
    diagnostics: list[Diagnostic]
    proposal: dict[str, Any] | None = None
    diff: str | None = None
    proposal_json: str | None = None
    proposal_path: Path | None = None
    diff_path: Path | None = None


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _diagnostic(
    code: str,
    message: str,
    *,
    path: str | None = None,
    rule_ids: list[str] | None = None,
    blocking: bool = True,
) -> Diagnostic:
    return Diagnostic(code, message, blocking, path, rule_ids)


def _walk(root: Path, target: Path) -> tuple[list[str], list[tuple[str, Path]]]:
    if target.is_symlink():
        raise ValueError(f"scope contains a symlink: {target}")
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"scope path resolves outside repository: {target}")
    paths = (
        [resolved]
        if resolved.is_file()
        else sorted(
            path
            for path in resolved.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and ".git" not in path.parts
            and not _ignored(path, root)
        )
    )
    return [resolved.relative_to(root).as_posix() or "."], [
        (path.relative_to(root).as_posix(), path) for path in paths
    ]


def _ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part.startswith(".") and part != "." for part in relative.parts)


def _raise_invalid_root(root: Path) -> Never:
    raise ValueError(f"repository root is not a directory: {root}")


def preview(
    repository_root: str | Path,
    invoking_cwd: str | Path,
    paths: list[str | Path],
    store_dir: str | Path,
    rules: list[RewriteRule],
) -> PreviewResult:
    diagnostics: list[Diagnostic] = []
    try:
        root = Path(repository_root).resolve(strict=True)
        cwd = Path(invoking_cwd).resolve(strict=True)
        if not root.is_dir():
            _raise_invalid_root(root)
    except (OSError, ValueError) as error:
        return PreviewResult(False, False, [_diagnostic("invalid_root", str(error))])
    if not paths:
        diagnostics.append(
            _diagnostic("invalid_scope", "at least one explicit path scope is required")
        )
    if not rules:
        diagnostics.append(
            _diagnostic("invalid_rules", "at least one rewrite rule is required")
        )

    normalized = sorted(
        rules, key=lambda rule: (rule.id, rule.language, rule.pattern, rule.replacement)
    )
    seen: set[str] = set()
    compiled: list[tuple[RewriteRule, str]] = []
    for rule in normalized:
        if not rule.id.strip():
            diagnostics.append(
                _diagnostic("invalid_rule_id", "rewrite rule id must not be empty")
            )
        elif rule.id in seen:
            diagnostics.append(
                _diagnostic(
                    "duplicate_rule_id",
                    f"rewrite rule id {rule.id!r} is used more than once",
                    rule_ids=[rule.id],
                )
            )
        seen.add(rule.id)
        try:
            lang = language_name(rule.language)
        except ValueError:
            diagnostics.append(
                _diagnostic(
                    "invalid_input",
                    f"unsupported language {rule.language!r}",
                    rule_ids=[rule.id],
                )
            )
            continue
        try:
            validate_rewrite_template(rule.replacement, rule.pattern)
        except ValueError as error:
            diagnostics.append(
                _diagnostic("invalid_rewrite_template", str(error), rule_ids=[rule.id])
            )
            continue
        compiled.append(
            (
                RewriteRule(
                    rule.id,
                    lang,
                    rule.pattern,
                    rule.replacement,
                    rule.inside,
                    rule.has,
                    rule.precedes,
                    rule.follows,
                ),
                lang,
            )
        )

    scope_names: list[str] = []
    snapshots: dict[str, tuple[Path, str, str]] = {}
    for raw in paths:
        target = Path(raw)
        target = target if target.is_absolute() else cwd / target
        try:
            scopes, files = _walk(root, target)
            scope_names.extend(scopes)
        except (OSError, ValueError) as error:
            diagnostics.append(_diagnostic("unsafe_path", str(error), path=str(target)))
            continue
        for relative, path in files:
            language = _language(path)
            if language is None:
                diagnostics.append(
                    _diagnostic(
                        "unsupported_file_type",
                        "unsupported file type — skipped",
                        path=relative,
                        blocking=False,
                    )
                )
                continue
            try:
                snapshots[relative] = (path, language, path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as error:
                diagnostics.append(
                    _diagnostic(
                        "read_failed",
                        f"cannot read source snapshot: {error}",
                        path=relative,
                    )
                )

    changes = []
    for relative, (_path, lang, source) in sorted(snapshots.items()):
        edits = []
        for rule, rule_lang in compiled:
            if lang != rule_lang:
                continue
            try:
                matches = list(
                    SgRoot(source, lang)
                    .root()
                    .find_all({"rule": {"pattern": rule.pattern}})
                )
                for node in matches:
                    rng = node.range()
                    start, end = rng.start.index, rng.end.index
                    start_byte = len(source[:start].encode())
                    end_byte = len(source[:end].encode())
                    capture_names = set(
                        re.findall(r"\$([A-Z][A-Z0-9_]*)", rule.pattern)
                    )
                    captures = {
                        name: {
                            "text": captured.text(),
                            "span": {
                                "start_byte": len(
                                    source[: captured.range().start.index].encode()
                                ),
                                "end_byte": len(
                                    source[: captured.range().end.index].encode()
                                ),
                            },
                        }
                        for name in capture_names
                        if (captured := node.get_match(name)) is not None
                    }
                    replacement = substitute_with_source(
                        rule.replacement, captures, source
                    )
                    edits.append(
                        (start_byte, end_byte, node.text(), replacement, rule.id)
                    )
            except (RuntimeError, ValueError) as error:
                diagnostics.append(
                    _diagnostic(
                        "pattern_error", str(error), path=relative, rule_ids=[rule.id]
                    )
                )
        if not edits:
            continue
        edits.sort()
        merged = []
        for start, end, original, replacement, rule_id in edits:
            if merged and start < merged[-1][1]:
                if (
                    start == merged[-1][0]
                    and end == merged[-1][1]
                    and replacement == merged[-1][3]
                ):
                    merged[-1][4].add(rule_id)
                else:
                    diagnostics.append(
                        _diagnostic(
                            "overlapping_edits",
                            "rewrite matches overlap",
                            path=relative,
                            rule_ids=[rule_id],
                        )
                    )
                continue
            merged.append([start, end, original, replacement, {rule_id}])
        source_bytes = source.encode()
        output = bytearray()
        cursor = 0
        spans = []
        for start, end, original, replacement, rule_ids in merged:
            output.extend(source_bytes[cursor:start])
            output.extend(replacement.encode())
            spans.append(
                {
                    "start_byte": start,
                    "end_byte": end,
                    "original": original,
                    "replacement": replacement,
                    "rule_ids": sorted(rule_ids),
                }
            )
            cursor = end
        output.extend(source_bytes[cursor:])
        replacement_content = output.decode()
        if replacement_content == source:
            continue
        changes.append(
            {
                "path": relative,
                "language": lang,
                "original_sha256": _sha(source_bytes),
                "replacement_sha256": _sha(bytes(output)),
                "original_content": source,
                "replacement_content": replacement_content,
                "match_spans": spans,
                "replacement_count": len(spans),
                "original_error_nodes": 0,
                "replacement_error_nodes": 0,
            }
        )

    diagnostics.sort(
        key=lambda item: (
            item.path or "",
            item.code,
            item.start_byte or -1,
            item.end_byte or -1,
            item.rule_ids or [],
            item.message,
        )
    )
    if any(item.blocking for item in diagnostics):
        return PreviewResult(False, False, diagnostics)
    if not changes:
        return PreviewResult(True, False, diagnostics)
    body = {
        "version": 1,
        "repository_root": str(root),
        "scope": sorted(set(scope_names)),
        "rules": [asdict(rule) for rule, _ in compiled],
        "files": changes,
        "diagnostics": [asdict(item) for item in diagnostics],
        "complete": True,
    }
    # Rust omits absent optional properties and empty optional arrays on the wire.
    body = _compact(body)
    proposal_id = _sha(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    )
    proposal = {"id": proposal_id, **body}
    pretty = json.dumps(proposal, ensure_ascii=False, indent=2) + "\n"
    diff = _unified(changes)
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(store, 0o700)
    proposal_path, diff_path = (
        store / f"{proposal_id}.json",
        store / f"{proposal_id}.diff",
    )
    _write_private(proposal_path, pretty)
    _write_private(diff_path, diff)
    return PreviewResult(
        True, True, diagnostics, proposal, diff, pretty, proposal_path, diff_path
    )


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact(item)
            for key, item in value.items()
            if item is not None and item != []
        }
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


def _language(path: Path) -> str | None:
    from varde_code.parse import language_for_path

    return language_for_path(path)


def _write_private(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _unified(changes: list[dict[str, Any]]) -> str:
    import difflib

    result = []
    for change in changes:
        result.extend(
            difflib.unified_diff(
                change["original_content"].splitlines(True),
                change["replacement_content"].splitlines(True),
                fromfile=f"a/{change['path']}",
                tofile=f"b/{change['path']}",
            )
        )
    return "".join(result)
