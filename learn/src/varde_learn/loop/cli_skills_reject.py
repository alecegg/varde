"""`varde learn skills reject <id>`: mark a proposal rejected."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.memory import store

from .help import help_text
from .improve import apply
from .improve import record as rec

VERB = "reject"


def run(args: list[str], io: object | None = None) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text(f"skills {VERB}"))
        return 0
    as_json = "--json" in args
    operands = [arg for arg in args if arg != "--json"]
    if len(operands) != 1 or operands[0].startswith("-"):
        return _fail(f"usage: skills {VERB} <id>", as_json, io)
    try:
        done = apply.reject(store.memory_root(Path.cwd()), operands[0])
    except (apply.ApplyError, rec.RecordError, OSError) as error:
        return _fail(str(error), as_json, io)
    if as_json:
        data = {"id": done.id, "state": done.state}
        _write(
            io,
            json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
            + "\n",
        )
    else:
        _write(io, f"rejected {done.id}\n")
    return 0


def _fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        body = json.dumps(
            tool_error(f"skills_{VERB}_failed", message), separators=(",", ":")
        )
        _write(io, body + "\n", error=True)
    else:
        _write(io, f"error: {message}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
