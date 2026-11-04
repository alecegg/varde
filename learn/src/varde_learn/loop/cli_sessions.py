"""`learn sessions calls`: the calls report plus the guardrail firing listing."""

from __future__ import annotations

import io as _io
import json
import sys
from types import SimpleNamespace

from . import cli_calls, cli_guardrails


def run_calls(args: list[str], io: object | None = None) -> int:
    """Run the calls report, then the guardrails section (`--dead`: only that)."""
    if any(token in {"-h", "--help"} for token in args):
        _write(io, cli_calls.help_text("sessions calls"))
        return 0
    dead = "--dead" in args
    shared = [arg for arg in args if arg != "--dead"]
    json_requested = "--json" in shared
    guardrails_out = _run(
        cli_guardrails.run, ["guardrails", *shared, *(["--dead"] if dead else [])]
    )
    if dead:
        return _forward(io, guardrails_out)
    calls_out = _run(cli_calls.run, ["calls", *shared])
    if calls_out.code != 0 or guardrails_out.code != 0:
        return _forward(io, calls_out if calls_out.code != 0 else guardrails_out)
    if json_requested:
        merged = json.loads(calls_out.out)
        merged["data"]["guardrails"] = json.loads(guardrails_out.out)["data"][
            "guardrails"
        ]
        _write(io, json.dumps(merged, separators=(",", ":"), sort_keys=True) + "\n")
    else:
        _write(io, calls_out.out + "Guardrails:\n" + guardrails_out.out)
    return 0


def _run(handler, argv: list[str]) -> SimpleNamespace:
    stdout, stderr = _io.StringIO(), _io.StringIO()
    code = handler(argv, SimpleNamespace(stdout=stdout, stderr=stderr))
    return SimpleNamespace(code=code, out=stdout.getvalue(), err=stderr.getvalue())


def _forward(io: object | None, result: SimpleNamespace) -> int:
    _write(io, result.out)
    if result.err:
        _write(io, result.err, error=True)
    return result.code


def _write(io: object | None, value: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    (stream or (sys.stderr if error else sys.stdout)).write(value)
