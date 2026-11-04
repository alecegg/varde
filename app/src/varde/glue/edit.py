"""Resolve app-level options for the AST edit command."""

from __future__ import annotations

import io as text_io
import json
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path

from varde_code.ast_edit import Options
from varde_code.ast_edit import run as run_ast_edit
from varde_core.io import Io
from varde_learn.knowledge.memory import MemoryPaths, Source


def run(args: Sequence[str], io: Io | None = None) -> int:
    """Run ``varde edit`` with project and proposal-store options."""
    argv = list(args)
    root = _repository_root()
    if root is None:
        return _report_error(
            argv, "repository_resolution_failed", "cannot resolve repository root"
        )
    preview = "preview" in argv
    output = _option_path(argv, "--out") if preview else None
    store_dir = output
    if preview and output is None:
        try:
            paths = MemoryPaths.resolve(root)
        except (OSError, ValueError) as error:
            return _report_error(
                argv,
                "working_store_resolution_failed",
                f"cannot resolve proposal working store: {error}",
            )
        store_dir = _proposal_store(paths)
    return _run_ast_edit(
        argv, io, Options(repository_root=root, store_dir=store_dir or Path())
    )


def _run_ast_edit(args: list[str], io: Io | None, options: Options) -> int:
    if "--json" not in args:
        return run_ast_edit(["varde", "edit", *args], io, options)
    captured = text_io.StringIO()
    with redirect_stdout(captured):
        result = run_ast_edit(["varde", "edit", *args], io, options)
    output = captured.getvalue()
    try:
        ordered = json.dumps(
            json.loads(output),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except TypeError, ValueError:
        sys.stdout.write(output)
    else:
        print(ordered)
    return result


def _repository_root() -> Path | None:
    try:
        from varde_toz.project import project_root

        return project_root()
    except OSError, RuntimeError, ValueError:
        return None


def _option_path(args: list[str], option: str) -> Path | None:
    for index, arg in enumerate(args[:-1]):
        if arg == option:
            return Path(args[index + 1])
    return None


def _proposal_store(paths: MemoryPaths) -> Path:
    if paths.working.source == Source.BUILTIN:
        return paths.config.parent / "ast-edit"
    return paths.working.path / "ast-edit"


def _report_error(args: list[str], code: str, message: str) -> int:
    if "--json" in args:
        from varde_core.envelope import tool_error

        print(tool_error(code, message))
    else:
        print(f"varde edit: {message}", file=sys.stderr)
    return 1
