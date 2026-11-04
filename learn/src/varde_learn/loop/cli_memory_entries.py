"""`varde learn memory` verbs over the Entry store: search, update, set-field,
delete, map and lint. Handlers only parse, call the `memory` library and render.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
from pathlib import Path

from varde_learn.memory import links, ops, search, searchindex, store
from varde_learn.memory.entry import SCOPES, Entry
from varde_learn.memory.expiry import expired_report
from varde_learn.memory.mapgen import build_map
from varde_learn.memory.rules import ERROR, Issue, lint_entry

VERBS = ("search", "update", "set-field", "delete", "map", "lint")


class UsageError(ValueError):
    """The command line is invalid."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise UsageError(message)


def _parser(verb: str) -> _Parser:
    return _Parser(
        prog=f"varde learn memory {verb}", add_help=False, allow_abbrev=False
    )


def parse_search(args: list[str]) -> argparse.Namespace:
    parser = _parser("search")
    parser.add_argument("--text", required=True)
    parser.add_argument("--topic", default="")
    parser.add_argument("--scope", choices=SCOPES)
    parser.add_argument("--field", action="append", default=[])
    parser.add_argument("--limit", type=int, default=search.DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def parse_update(args: list[str]) -> argparse.Namespace:
    parser = _parser("update")
    parser.add_argument("id")
    parser.add_argument("--expected-version", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--file", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def parse_set_field(args: list[str]) -> argparse.Namespace:
    parser = _parser("set-field")
    parser.add_argument("id")
    parser.add_argument("key")
    parser.add_argument("value")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def parse_delete(args: list[str]) -> argparse.Namespace:
    parser = _parser("delete")
    parser.add_argument("id")
    parser.add_argument("--expected-version")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def parse_map(args: list[str]) -> argparse.Namespace:
    parser = _parser("map")
    parser.add_argument("--write", type=Path, help="write the map to this file")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def parse_lint(args: list[str]) -> argparse.Namespace:
    parser = _parser("lint")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


PARSERS = {
    "search": parse_search,
    "update": parse_update,
    "set-field": parse_set_field,
    "delete": parse_delete,
    "map": parse_map,
    "lint": parse_lint,
}


def exit_code(error: ops.OpsError) -> int:
    """Not found and conflicts exit 1; everything else is a usage problem."""
    return 1 if error.kind in ("not_found", "conflict") else 2


def parse_filters(fields: list[str]) -> tuple[tuple[str, str], ...]:
    pairs = [field.partition("=") for field in fields]
    for field, (key, separator, _) in zip(fields, pairs, strict=True):
        if not separator or not key:
            raise UsageError(f"invalid --field `{field}`: expected `key=value`")
    return tuple((key, value) for key, _, value in pairs)


def hit_row(hit: search.Hit) -> dict:
    return {
        "id": hit.slug,
        "type": hit.type,
        "score": hit.score,
        "preview": hit.preview,
        "path": str(hit.path),
    }


def hit_line(hit: search.Hit) -> str:
    return f"{hit.slug} | {hit.type} | {hit.score} | {hit.preview}"


def lint_text(issues: list[Issue]) -> str:
    return "\n".join(
        f"{i.severity} {i.code} {i.path or '-'}: {i.message}" for i in issues
    )


def lint_all(entries: list[Entry], load_issues: list[Issue]) -> list[Issue]:
    """Unreadable files, each entry's own issues (as stored) and link issues."""
    issues = list(load_issues)
    for entry in entries:
        issues += [
            Issue(i.severity, i.code, i.message, entry.id)
            for i in lint_entry(entry, entry)
        ]
    return issues + links.lint_links(entries)


def expired_ids(entries: list[Entry], today: date) -> list[str]:
    return [e.id for e in expired_report(entries, today)]


# ---- handlers -------------------------------------------------------------


def _root() -> Path:
    return store.memory_root(Path.cwd())


def _source(root: Path) -> searchindex.Source:
    return searchindex.memory_source(root)


def handle_search(args: argparse.Namespace) -> dict:
    root = _root()
    options = search.SearchOptions(
        filters=parse_filters(args.field),
        topic=args.topic,
        scopes=(args.scope,) if args.scope else (),
        limit=args.limit,
    )
    hits = search.search(
        _source(root), args.text, options, searchindex.index_file_for(root)
    )
    return {
        "hits": [hit_row(hit) for hit in hits],
        "text": "\n".join(hit_line(hit) for hit in hits),
    }


def _text_of(args: argparse.Namespace) -> str:
    if args.file is None:
        return args.text
    try:
        return args.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f"cannot read {args.file}: {error}") from error


def _result(verb: str, entry_id: str, result: ops.OpResult) -> dict:
    warnings = [i for i in result.issues if i.severity != ERROR]
    return {
        "id": entry_id,
        "path": str(result.path),
        "version": result.version,
        "issues": [asdict(i) for i in warnings],
        "text": "\n".join([f"{verb} {entry_id}", *_warning_lines(warnings)]),
    }


def _warning_lines(issues: list[Issue]) -> list[str]:
    return [f"{i.severity}: {i.message}" for i in issues]


def handle_update(args: argparse.Namespace) -> dict:
    root = _root()
    ref = ops.resolve_ref(root, args.id)
    result = ops.update_entry(
        root, ref, args.expected_version, {"text": _text_of(args)}
    )
    return _result("updated", args.id, result)


def handle_set_field(args: argparse.Namespace) -> dict:
    root = _root()
    ref = ops.resolve_ref(root, args.id)
    result = ops.set_field(root, ref, args.expected_version, (args.key, args.value))
    return _result("updated", args.id, result)


def handle_delete(args: argparse.Namespace) -> dict:
    root = _root()
    ref = ops.resolve_ref(root, args.id)
    version = args.expected_version or ops.read_stored(root, ref).version
    result = ops.delete_entry(root, ref, version)
    notes = [f"linked from {path}" for path in result.linked_by]
    return {
        "id": args.id,
        "path": str(result.path),
        "linked_by": list(result.linked_by),
        "text": "\n".join([f"deleted {args.id}", *notes]),
    }


def handle_map(args: argparse.Namespace) -> dict:
    root = _root()
    entries, _ = store.load_report(root)
    text = build_map(root, entries, args.write)
    written = str(args.write) if args.write else ""
    return {"map": text, "written": written, "text": text.rstrip("\n")}


def handle_lint(args: argparse.Namespace) -> dict:
    entries, load_issues = store.load_report(_root())
    issues = lint_all(entries, load_issues)
    return {
        "issues": [asdict(i) for i in issues],
        "errors": sum(i.severity == ERROR for i in issues),
        "text": lint_text(issues),
    }


HANDLERS = {
    "search": handle_search,
    "update": handle_update,
    "set-field": handle_set_field,
    "delete": handle_delete,
    "map": handle_map,
    "lint": handle_lint,
}
