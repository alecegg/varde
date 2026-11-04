"""``varde learn store status|migrate|verify|retire|prune``: per-domain store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from varde_core.envelope import success, tool_error
from varde_data import calls_store
from varde_data.errors import DataError
from varde_data.learn_registry import (
    LEARN_DOMAINS,
    HandlersMissing,
    handler,
    source_files_present,
)
from varde_data.learn_store_mode import (
    exclusive_store_lock,
    flip_domain_locked,
    learn_db_path,
    read_learn_mode,
    shared_store_lock,
)

from .calls_retention import prune_calls, retention_days
from .errors import LearnError
from .help import help_text
from .store.paths import resolve_store_dir, validate_store_path

_ACTIONS = ("status", "migrate", "verify", "retire", "prune")
_DRY_RUN_ACTIONS = ("migrate", "prune")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:
        raise ValueError(message)


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "store":
        args.pop(0)
    if not args or any(token in {"-h", "--help"} for token in args):
        _write(io, help_text("store"))
        return 0 if args else 2
    json_requested = "--json" in args
    try:
        parsed = _parse(args)
        root = resolve_store_dir()
        validate_store_path(root)
        data = _ACTIONS_TABLE[parsed.action](root, parsed)
    except (ValueError, LearnError, DataError, HandlersMissing) as error:
        _error(io, error, json_requested)
        return 2
    if json_requested:
        _write(io, json.dumps(success(data, {"truncated": False})) + "\n")
    else:
        _write(io, json.dumps(data, indent=2, sort_keys=True) + "\n")
    return 0 if data.get("ok", True) else 1


def _parse(args: list[str]) -> argparse.Namespace:
    parser = _Parser(prog="varde learn store", add_help=False)
    parser.add_argument("action", choices=_ACTIONS)
    parser.add_argument("--domain", choices=sorted(LEARN_DOMAINS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int)
    parser.add_argument("--vacuum", action="store_true")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(args)
    if parsed.action != "status" and parsed.domain is None:
        raise ValueError(f"{parsed.action} requires --domain")
    if parsed.dry_run and parsed.action not in _DRY_RUN_ACTIONS:
        raise ValueError("--dry-run applies only to migrate and prune")
    if (parsed.days is not None or parsed.vacuum) and parsed.action != "prune":
        raise ValueError("--days and --vacuum apply only to prune")
    if parsed.days is not None and parsed.days < 1:
        raise ValueError("--days must be a positive integer")
    return parsed


def _status(root: Path, parsed: argparse.Namespace) -> dict[str, Any]:
    record = read_learn_mode(root)
    names = [parsed.domain] if parsed.domain else list(LEARN_DOMAINS)
    domains = {
        name: {
            "mode": record.mode(name),
            "rows": _rows(root, name),
            "files_present": source_files_present(root, name),
        }
        for name in names
    }
    database = learn_db_path(root)
    if "calls" in domains and domains["calls"]["mode"] == "sqlite":
        domains["calls"].update(calls_store.usage(root))
    return {
        "database": str(database) if database.is_file() else None,
        "generation": record.generation,
        "domains": domains,
    }


def _rows(root: Path, name: str) -> int:
    try:
        return int(handler(name, "rows")(root))
    except HandlersMissing:
        return 0


def _migrate(root: Path, parsed: argparse.Namespace) -> dict[str, Any]:
    name = parsed.domain
    migrate = handler(name, "migrate")
    if parsed.dry_run:
        with shared_store_lock(root):
            _refuse_if_sqlite(root, name)
            return {"domain": name, "dry_run": True, **migrate(root, dry_run=True)}
    with exclusive_store_lock(root):
        _refuse_if_sqlite(root, name)
        result = migrate(root, dry_run=False)
        if not result.get("ok", False):
            return {"domain": name, **result, "ok": False}
        record = flip_domain_locked(root, name, "sqlite")
    return {"domain": name, **result, "ok": True, "generation": record.generation}


def _refuse_if_sqlite(root: Path, name: str) -> None:
    if read_learn_mode(root).mode(name) == "sqlite":
        raise ValueError(f"{name} is already on sqlite")


def _verify(root: Path, parsed: argparse.Namespace) -> dict[str, Any]:
    verify = handler(parsed.domain, "verify")
    with shared_store_lock(root):
        result = verify(root)
    return {"domain": parsed.domain, **result}


def _retire(root: Path, parsed: argparse.Namespace) -> dict[str, Any]:
    name = parsed.domain
    if read_learn_mode(root).mode(name) != "sqlite":
        raise ValueError(f"{name} is not on sqlite; migrate it first")
    with exclusive_store_lock(root):
        verified = handler(name, "verify")(root)
        if not verified.get("ok", False):
            return {"domain": name, **verified, "ok": False, "retired": False}
        result = handler(name, "retire")(root)
    return {"domain": name, **result, "ok": True, "retired": True}


def _prune(root: Path, parsed: argparse.Namespace) -> dict[str, Any]:
    if parsed.domain != "calls":
        raise ValueError("prune applies only to --domain calls")
    days = parsed.days if parsed.days is not None else retention_days()
    result = prune_calls(root, days, dry_run=parsed.dry_run, vacuum=parsed.vacuum)
    return {"domain": "calls", "days": days, **result}


_ACTIONS_TABLE = {
    "status": _status,
    "migrate": _migrate,
    "verify": _verify,
    "retire": _retire,
    "prune": _prune,
}


def _error(io: object | None, error: Exception, as_json: bool) -> None:
    if as_json:
        code = getattr(error, "code", "usage_error")
        _write(io, json.dumps(tool_error(code, str(error))) + "\n", True)
    else:
        _write(io, f"error: {error}\n", True)


def _write(io: object | None, value: str, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    (stream or getattr(sys, "stderr" if error else "stdout")).write(value)
