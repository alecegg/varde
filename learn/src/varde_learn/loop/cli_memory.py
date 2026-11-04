"""`varde learn memory <verb>`: scoped memory entries."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from varde_core.envelope import negative_result, success, tool_error

from varde_learn.knowledge.memory_config import load_config
from varde_learn.knowledge.occ import version
from varde_learn.memory import ops, share, store
from varde_learn.memory.entry import SCOPES, Entry, EntryError, is_slug
from varde_learn.memory.index import IndexLine, build_index, render_index
from varde_learn.memory.rules import ERROR, lint_entry

from . import cli_memory_entries as entries_cli
from .cli_memory_entries import UsageError
from .cli_memory_list import counts_lines, expired_lines, scope_counts
from .help import help_text

LOCAL_VERBS = ("add", "list", "show", "retire", "reset", *entries_cli.VERBS)
# verb -> module created by a later task; loaded lazily.
LATER_VERBS = {
    "surface": "cli_memory_surface",
    "promote": "cli_memory_share",
    "pull": "cli_memory_share",
    "migrate": "cli_memory_migrate",
}
VERBS = (*LOCAL_VERBS, *LATER_VERBS)


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "memory":
        args.pop(0)
    if args[:1] in (["-h"], ["--help"]):
        _write(io, help_text("memory"))
        return 0
    if not args:
        _write(io, help_text("memory"), error=True)
        return 2
    verb, rest = args[0], args[1:]
    if verb not in VERBS:
        _write(io, f"error: unknown memory command '{verb}'\n", error=True)
        return 2
    if any(arg in {"-h", "--help"} for arg in rest):
        _write(io, help_text(f"memory {verb}"))
        return 0
    if verb in LATER_VERBS:
        return _run_later(verb, rest, io)
    return _run_local(verb, rest, io)


def _run_later(verb: str, rest: list[str], io: object | None) -> int:
    name = LATER_VERBS[verb]
    try:
        module = importlib.import_module(f"{__package__}.{name}")
    except ModuleNotFoundError as error:
        if error.name != f"{__package__}.{name}":
            raise
        _write(io, f"error: memory {verb}: not yet available\n", error=True)
        return 2
    return module.run([verb, *rest], io)


def _run_local(verb: str, rest: list[str], io: object | None) -> int:
    wants_json = "--json" in rest
    try:
        parsed = _PARSERS[verb](rest)
        data = _HANDLERS[verb](parsed)
    except (UsageError, EntryError, ops.OpsError, OSError) as error:
        return _fail(error, verb, wants_json, io)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    return _emit(verb, data, wants_json, io)


def _fail(error: Exception, verb: str, wants_json: bool, io: object | None) -> int:
    code = 1 if isinstance(error, LookupError) else 2
    if isinstance(error, ops.OpsError):
        code = entries_cli.exit_code(error)
    if wants_json:
        payload = tool_error(f"memory_{verb}_failed", str(error))
        _write(io, json.dumps(payload, separators=(",", ":")) + "\n", error=True)
    else:
        _write(io, f"error: {error}\n", error=True)
    return code


def _emit(verb: str, data: dict, wants_json: bool, io: object | None) -> int:
    if verb == "lint" and data["errors"]:
        return _emit_lint_failure(data, wants_json, io)
    if wants_json:
        envelope = success(data, {"truncated": False})
        _write(io, json.dumps(envelope, separators=(",", ":")) + "\n")
    else:
        _write(io, data["text"] + ("\n" if data["text"] else ""))
    return 0


def _emit_lint_failure(data: dict, wants_json: bool, io: object | None) -> int:
    """Lint errors exit 2; the report stays on stdout."""
    if wants_json:
        message = f"{data['errors']} lint errors"
        envelope = negative_result(
            "memory_lint_failed", message, data, {"truncated": False}
        )
        _write(io, json.dumps(envelope, separators=(",", ":")) + "\n")
    else:
        _write(io, data["text"] + "\n")
    return 2


# ---- parsers -------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise UsageError(message)


def _parser(verb: str) -> _Parser:
    return _Parser(
        prog=f"varde learn memory {verb}", add_help=False, allow_abbrev=False
    )


def _parse_add(args: list[str]) -> argparse.Namespace:
    parser = _parser("add")
    parser.add_argument("--scope", required=True, choices=SCOPES)
    parser.add_argument("--key", default="")
    parser.add_argument("--project", default="")
    parser.add_argument("--text", required=True)
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--source", default="cli")
    parser.add_argument("--no-surface", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--harness-version", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def _parse_list(args: list[str]) -> argparse.Namespace:
    parser = _parser("list")
    parser.add_argument("--scope", choices=SCOPES)
    parser.add_argument("--key")
    parser.add_argument("--skill")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--expired", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def _parse_id(verb: str, args: list[str]) -> argparse.Namespace:
    parser = _parser(verb)
    parser.add_argument("id")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def _parse_reset(args: list[str]) -> argparse.Namespace:
    parser = _parser("reset")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--harness-version", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


_PARSERS = {
    "add": _parse_add,
    "list": _parse_list,
    "show": lambda args: _parse_id("show", args),
    "retire": lambda args: _parse_id("retire", args),
    "reset": _parse_reset,
    **entries_cli.PARSERS,
}


# ---- pure selection ------------------------------------------------------


def resolve_filter(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Return (scope, key) for `list`; `--skill` means scope skill and that key."""
    if args.skill is None:
        return args.scope, args.key
    if args.scope not in (None, "skill") or args.key not in (None, args.skill):
        raise UsageError("--skill conflicts with --scope/--key")
    return "skill", args.skill


def select_entries(
    entries: list[Entry], scope: str | None, key: str | None, *, include_inactive: bool
) -> list[Entry]:
    return [
        e
        for e in entries
        if (include_inactive or e.status == "active")
        and (scope is None or e.scope == scope)
        and (key is None or e.scope_key == key)
    ]


def entries_to_archive(
    entries: list[Entry], agent: str, model: str, harness_version: str
) -> list[Entry]:
    return [
        e
        for e in entries
        if e.scope == "agent"
        and e.scope_key == agent
        and e.status == "active"
        and (e.model != model or e.harness_version != harness_version)
    ]


def default_key(scope: str, key: str, cwd: Path) -> str:
    if scope == "project" and not key:
        return store.current_project_key(cwd)
    return key


# ---- handlers ------------------------------------------------------------


def _root() -> Path:
    return store.memory_root(Path.cwd())


def _handle_add(args: argparse.Namespace) -> dict:
    key = default_key(args.scope, args.key, Path.cwd())
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = Entry(
        id=store.generate_id(args.text, args.scope, created),
        scope=args.scope,
        scope_key=key,
        text=args.text,
        source=args.source,
        created=created,
        tags=tuple(args.tag),
        project=args.project,
        model=args.model if args.scope == "agent" else "",
        harness_version=args.harness_version if args.scope == "agent" else "",
        surface=not args.no_surface,
    )
    errors = [i.message for i in lint_entry(entry, None) if i.severity == ERROR]
    if errors:
        raise EntryError("; ".join(errors))
    path = store.write_entry(_root(), entry)
    return {
        "id": entry.id,
        "path": str(path),
        "version": version(path.read_bytes()),
        "text": f"added {entry.id}",
    }


def _handle_list(args: argparse.Namespace) -> dict:
    scope, key = resolve_filter(args)
    stored = list(store.load_entries(_root()))
    if args.expired:
        return _handle_expired(stored)
    local = select_entries(stored, scope, key, include_inactive=args.all)
    loaded, dropped = share.read_shared()
    share.warn_dropped(dropped)
    shared = select_entries(loaded, scope, key, include_inactive=args.all)
    lines, shared_lines = build_index(local), share.shared_index(shared)
    rows = [_row(line, shared=False) for line in lines]
    rows += [_row(line, shared=True) for line in shared_lines]
    text = [render_index(lines)] if lines else []
    text += [render_index([line]) + " | shared" for line in shared_lines]
    limit = _scope_limit()
    counts = scope_counts(stored)
    for line in counts_lines(counts, limit):
        print(line, file=sys.stderr)
    return {"entries": rows, "counts": counts, "text": "\n".join(text)}


def _scope_limit() -> int:
    limit, error = load_config().memory.scope_warn()
    if error:
        print(f"warning: {error}", file=sys.stderr)
    return limit


def _handle_expired(stored: list[Entry]) -> dict:
    lines = expired_lines(stored, datetime.now(UTC).date())
    return {"expired": lines, "text": "\n".join(lines)}


def _row(line: IndexLine, *, shared: bool) -> dict:
    return asdict(line) | {"tags": list(line.tags), "shared": shared}


def _find(entry_id: str) -> Entry:
    if entry_id.startswith(share.SHARED_PREFIX):
        raise UsageError(
            "shared entries change only by reviewed commit in the shared repo"
        )
    if not is_slug(entry_id):
        raise UsageError(f"invalid id: {entry_id!r}")
    found = [e for e in store.load_entries(_root()) if e.id == entry_id]
    if not found:
        raise _NotFound(f"no memory entry with id {entry_id}")
    if len(found) > 1:
        scopes = ", ".join(f"{e.scope}/{e.scope_key}".rstrip("/") for e in found)
        raise UsageError(f"id {entry_id} is ambiguous: {scopes}")
    return found[0]


class _NotFound(LookupError, EntryError):
    """No entry has the requested id."""


def _find_shared(entry_id: str) -> Entry:
    wanted = entry_id.removeprefix(share.SHARED_PREFIX)
    found = [e for e in share.load_shared() if e.id == wanted]
    if not found:
        raise _NotFound(f"no shared memory entry with id {wanted}")
    return replace(found[0], id=entry_id)


def _handle_show(args: argparse.Namespace) -> dict:
    if args.id.startswith(share.SHARED_PREFIX):
        entry = _find_shared(args.id)
    else:
        entry = _find(args.id)
    header = [
        f"id: {entry.id}",
        f"scope: {entry.scope}",
        f"scope_key: {entry.scope_key}",
        f"status: {entry.status}",
        f"created: {entry.created}",
        f"source: {entry.source}",
        f"tags: {','.join(entry.tags)}",
    ]
    if entry.project:
        header.append(f"project: {entry.project}")
    if entry.scope == "agent":
        header += [f"model: {entry.model}", f"harness_version: {entry.harness_version}"]
    data = asdict(entry) | {"tags": list(entry.tags)}
    data.pop("extra", None)
    version = _stored_version(entry)
    if version:
        header.append(f"version: {version}")
    return {
        "entry": data,
        "version": version,
        "text": "\n".join(header) + "\n\n" + entry.text,
    }


def _stored_version(entry: Entry) -> str:
    """OCC version of a local entry's file; empty for a shared entry."""
    if entry.id.startswith(share.SHARED_PREFIX):
        return ""
    ref = ops.EntryRef(entry.scope, entry.scope_key, entry.id)
    return ops.read_stored(_root(), ref).version


def _handle_retire(args: argparse.Namespace) -> dict:
    entry = _find(args.id)
    store.set_status(_root(), entry, "retired")
    return {"id": entry.id, "status": "retired", "text": f"retired {entry.id}"}


def _handle_reset(args: argparse.Namespace) -> dict:
    if args.agent.startswith(share.SHARED_PREFIX):
        raise UsageError("shared entries change only by reviewed commit")
    root = _root()
    targets = entries_to_archive(
        list(store.load_entries(root)), args.agent, args.model, args.harness_version
    )
    if not args.dry_run:
        for entry in targets:
            store.write_entry(root, replace(entry, status="archived"), overwrite=True)
    ids = [e.id for e in targets]
    verb = "would archive" if args.dry_run else "archived"
    return {
        "archived": ids,
        "dry_run": args.dry_run,
        "text": f"{verb} {len(ids)} entries" + "".join(f"\n{i}" for i in ids),
    }


_HANDLERS = {
    "add": _handle_add,
    "list": _handle_list,
    "show": _handle_show,
    "retire": _handle_retire,
    "reset": _handle_reset,
    **entries_cli.HANDLERS,
}


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
