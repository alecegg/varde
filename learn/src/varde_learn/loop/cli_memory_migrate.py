"""`varde learn memory migrate`: one-shot import of memory-tier decisions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.knowledge.memory import MemoryPaths
from varde_learn.memory import migrate, store

from . import cli_memory_knowledge as knowledge_cli
from .store.paths import resolve_store_dir


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ValueError(message)


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args[:1] == ["migrate"]:
        args.pop(0)
    wants_json = "--json" in args
    try:
        parsed = _parse(args)
        if parsed.knowledge is not None:
            return _run_knowledge(parsed, wants_json, io)
        report = _migrate(parsed)
    except (ValueError, OSError) as error:
        return _fail(error, wants_json, io)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    data = asdict(report) | {"counts": report.counts(), "text": report.render()}
    if wants_json:
        _write(
            io,
            json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
            + "\n",
        )
    else:
        _write(io, report.render() + "\n")
    return 0


def _parse(args: list[str]) -> argparse.Namespace:
    parser = _Parser(
        prog="varde learn memory migrate", add_help=False, allow_abbrev=False
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--knowledge", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--undo", action="store_true")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(args)
    if parsed.knowledge is None and (parsed.apply or parsed.undo):
        raise ValueError("--apply and --undo need --knowledge <bundle>")
    if parsed.dry_run and (parsed.apply or parsed.undo):
        raise ValueError("--dry-run cannot combine with --apply or --undo")
    return parsed


def _run_knowledge(
    args: argparse.Namespace, wants_json: bool, io: object | None
) -> int:
    bundle = args.knowledge
    if not bundle.is_dir():
        raise ValueError(f"not a directory: {bundle}")
    root = store.memory_root(Path.cwd())
    if args.undo:
        data = knowledge_cli.undo_data(root, bundle)
    else:
        project_root = args.project_root or Path.cwd()
        data = knowledge_cli.plan_data(
            root, bundle, store.current_project_key(project_root), apply=args.apply
        )
    if wants_json:
        envelope = success(data, {"truncated": False})
        _write(io, json.dumps(envelope, separators=(",", ":")) + "\n")
    else:
        _write(io, data["text"] + "\n")
    return 0


def _migrate(args: argparse.Namespace) -> migrate.Report:
    log = resolve_store_dir() / migrate.OLD_LOG
    cwd = Path.cwd()
    paths = MemoryPaths.resolve(cwd)
    report = migrate.migrate(
        migrate.read_rows(log),
        store.memory_root(cwd),
        project_of=migrate.make_project_of(paths, args.project_root, cwd),
        applied_in_place=migrate.make_applied_in_place(paths),
        dry_run=args.dry_run,
    )
    if log.exists() and not args.dry_run and report.complete():
        log.rename(log.with_name(migrate.MIGRATED_LOG))
        report.renamed = True
    return report


def _fail(error: Exception, wants_json: bool, io: object | None) -> int:
    if wants_json:
        payload = tool_error("memory_migrate_failed", str(error))
        _write(io, json.dumps(payload, separators=(",", ":")) + "\n", error=True)
    else:
        _write(io, f"error: {error}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
