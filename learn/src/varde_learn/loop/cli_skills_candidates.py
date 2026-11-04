"""`varde learn skills candidates [<dir>...]`: report-only ranking."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from varde_core.envelope import success, tool_error

from varde_learn.docs import baseline_cmd

from .help import help_text
from .improve import candidates, promotion, tool_entry

Demand = Callable[[], dict[str, Any]]


def run(args: list[str], io: object | None = None, demand: Demand | None = None) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text("skills candidates"))
        return 0
    as_json = "--json" in args
    operands, baselines_dir = _split_baselines([arg for arg in args if arg != "--json"])
    if any(arg.startswith("-") for arg in operands):
        return _fail(f"unknown option '{operands[0]}'", as_json, io)
    try:
        dirs, registry_roots = _dirs(operands)
        targets = candidates.gather_targets(dirs)
        report = (demand or promotion.read_demand_report)()
        groups = candidates.rank(
            targets,
            report,
            candidates.registered_steps(registry_roots),
            baselines=_baseline_states(baselines_dir),
        )
    except (OSError, ValueError, KeyError, baseline_cmd.BaselineError) as error:
        return _fail(str(error), as_json, io)
    if as_json:
        body = success(candidates.to_json_data(groups), {"truncated": False})
        _write(io, json.dumps(body, separators=(",", ":")) + "\n")
    else:
        _write(io, candidates.format_text(groups))
    return 0


def _split_baselines(args: list[str]) -> tuple[list[str], Path | None]:
    operands: list[str] = []
    found: Path | None = None
    queue = list(args)
    while queue:
        arg = queue.pop(0)
        if arg == "--baselines" and queue:
            found = Path(queue.pop(0))
        else:
            operands.append(arg)
    return operands, found


def _baseline_states(directory: Path | None) -> dict[str, candidates.BaselineState]:
    """Newest baseline entry per skill, from the installed providers' files."""
    if directory is None:
        return {}
    rows = baseline_cmd.statuses(
        directory, Path.cwd(), None, baseline_cmd.provider_packages()
    )
    return {
        row.skill: candidates.BaselineState(
            row.baseline["gen"],
            row.drift is False and row.tree_hash_match is not False,
        )
        for row in rows
        if row.baseline is not None
    }


def _dirs(operands: list[str]) -> tuple[list[Path], list[Path]]:
    """Dirs to size and roots holding registry rows; default: synced skills first."""
    if operands:
        explicit = [Path(arg) for arg in operands]
        return explicit, explicit
    dirs = [tool_entry.require_sync_target(), *tool_entry.package_roots()]
    return dirs, tool_entry.module_roots()


def _fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        body = json.dumps(
            tool_error("skills_candidates_failed", message), separators=(",", ":")
        )
        _write(io, body + "\n", error=True)
    else:
        _write(io, f"error: {message}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
