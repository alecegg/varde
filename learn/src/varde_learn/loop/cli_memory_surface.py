"""`varde learn memory surface`: pointer text for a session start."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.knowledge.memory_config import MemoryConfigError, load_config
from varde_learn.memory import share, store
from varde_learn.memory.surface import render_surface, select_entries


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ValueError(message)


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args[:1] == ["surface"]:
        args.pop(0)
    wants_json = "--json" in args
    try:
        parsed = _parse(args)
        data = _surface(parsed, io)
    except (ValueError, MemoryConfigError, OSError) as error:
        return _fail(error, wants_json, io)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    if wants_json:
        envelope = success(data, {"truncated": data["omitted"] > 0})
        _write(io, json.dumps(envelope, separators=(",", ":")) + "\n")
    else:
        _write(io, data["text"] + "\n")
    return 0


def _parse(args: list[str]) -> argparse.Namespace:
    parser = _Parser(
        prog="varde learn memory surface", add_help=False, allow_abbrev=False
    )
    parser.add_argument("--agent")
    parser.add_argument("--skill")
    parser.add_argument("--project")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(args)
    if parsed.budget is not None and parsed.budget < 1:
        raise ValueError("--budget must be a positive integer")
    return parsed


def _surface(args: argparse.Namespace, io: object | None) -> dict:
    cwd = Path.cwd()
    budget = args.budget or _configured_budget(io)
    root, current = store.memory_root_and_project(cwd)
    project = args.project or current
    entries = list(store.load_entries(root))
    shared = share.load_shared()
    text, omitted = render_surface(
        entries,
        agent=args.agent,
        skill=args.skill,
        project=project,
        budget=budget,
        root=str(root),
        shared=shared,
    )
    shown = select_entries([*entries, *shared], args.agent, args.skill, project)
    return {
        "text": text,
        "omitted": omitted,
        "project": project,
        "selected": len(shown),
    }


def _configured_budget(io: object | None) -> int:
    budget, error = load_config().memory.budget_chars()
    if error:
        _write(io, f"warning: [memory] budget: {error}\n", error=True)
    return budget


def _fail(error: Exception, wants_json: bool, io: object | None) -> int:
    if wants_json:
        payload = tool_error("memory_surface_failed", str(error))
        _write(io, json.dumps(payload, separators=(",", ":")) + "\n", error=True)
    else:
        _write(io, f"error: {error}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
