"""`varde learn skills accept <id>`: apply a stored proposal."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.memory import store

from .help import help_text
from .improve import apply, tool_entry
from .improve import record as rec

VERB = "accept"


def run(
    args: list[str],
    io: object | None = None,
    regenerate: apply.Regenerate | None = None,
    roots: Sequence[Path] | None = None,
    sync: Path | None = None,
) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text(f"skills {VERB}"))
        return 0
    as_json = "--json" in args
    operands, option_roots = _split_roots([arg for arg in args if arg != "--json"])
    if len(operands) != 1 or operands[0].startswith("-"):
        return _fail(f"usage: skills {VERB} <id> [--root <dir>]...", as_json, io)
    roots = roots if roots is not None else (option_roots or None)
    try:
        sync = sync or (None if roots is not None else tool_entry.require_sync_target())
        root = store.memory_root(Path.cwd())
        record = rec.read_record(root, operands[0])
        if not as_json:
            _write(io, f"token delta {record.token_delta:+d} per run\n")
        done, skipped = apply.accept_with_notes(
            root, operands[0], regenerate, roots, sync
        )
    except (apply.ApplyError, rec.RecordError, OSError, ValueError) as error:
        return _fail(str(error), as_json, io)
    if as_json:
        data = {
            "id": done.id,
            "state": done.state,
            "token_delta": done.token_delta,
            "hand_edited_unrecorded": skipped,
        }
        _write(
            io,
            json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
            + "\n",
        )
    else:
        _write(io, f"applied {done.id}\n")
        if skipped:
            _write(
                io,
                "hand-edited, loop-hash not recorded: " + ", ".join(skipped) + "\n",
            )
    return 0


def _split_roots(args: list[str]) -> tuple[list[str], list[Path]]:
    """Operands and the package-layout roots given by repeated `--root <dir>`."""
    operands: list[str] = []
    found: list[Path] = []
    queue = list(args)
    while queue:
        arg = queue.pop(0)
        if arg == "--root" and queue:
            found.append(Path(queue.pop(0)))
        else:
            operands.append(arg)
    return operands, found


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
