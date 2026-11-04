"""`varde learn memory promote|pull`: the shared memory store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.knowledge.memory_config import MemoryConfigError, load_config
from varde_learn.memory import share, store
from varde_learn.memory.entry import EntryError, is_slug


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ValueError(message)


def run(argv: list[str], io: object | None = None) -> int:
    verb, rest = argv[0], argv[1:]
    wants_json = "--json" in rest
    try:
        data = _HANDLERS[verb](_parse(verb, rest))
    except (ValueError, share.ShareError, EntryError, MemoryConfigError, OSError) as e:
        return _fail(verb, e, wants_json, io)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    if wants_json:
        envelope = success(data, {"truncated": False})
        _write(io, json.dumps(envelope, separators=(",", ":")) + "\n")
    else:
        _write(io, data["text"] + "\n")
    return 0


def _parse(verb: str, args: list[str]) -> argparse.Namespace:
    parser = _Parser(
        prog=f"varde learn memory {verb}", add_help=False, allow_abbrev=False
    )
    if verb == "promote":
        parser.add_argument("id")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(args)


def _handle_promote(args: argparse.Namespace) -> dict:
    if not is_slug(args.id):
        raise ValueError(f"invalid id: {args.id!r}")
    share.require_checkout(share.checkout_path())
    root = store.memory_root(Path.cwd())
    found = [e for e in store.load_entries(root) if e.id == args.id]
    if not found:
        raise ValueError(f"no local memory entry with id {args.id}")
    branch = share.promote(found[0], root)
    return {
        "id": args.id,
        "branch": branch,
        "text": f"promoted {args.id} on branch {branch}; push it and open a review",
    }


def _handle_pull(_: argparse.Namespace) -> dict:
    checkout = share.checkout_path()
    if not (checkout / ".git").exists():
        source, error = load_config().memory.shared()
        if error:
            raise ValueError(f"{error}; set `[memory] shared` in config.toml")
        action = share.pull(source)
    else:
        action = share.pull("")
    entries, dropped = share.read_shared()
    share.warn_dropped(dropped)
    count = len(entries)
    return {
        "action": action,
        "entries": count,
        "text": f"{action}; {count} shared entries",
    }


_HANDLERS = {"promote": _handle_promote, "pull": _handle_pull}


def _fail(verb: str, error: Exception, wants_json: bool, io: object | None) -> int:
    if wants_json:
        payload = tool_error(f"memory_{verb}_failed", str(error))
        _write(io, json.dumps(payload, separators=(",", ":")) + "\n", error=True)
    else:
        _write(io, f"error: {error}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
