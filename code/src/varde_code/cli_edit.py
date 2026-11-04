"""CLI adapter and help snapshots for AST edit commands."""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from varde_core.paths import varde_config_dir

from .ast_edit.cli import Options
from .ast_edit.cli import run as run_ast_edit

_HELP_FILES = {
    "": "edit_preview.txt",
    "preview": "edit_preview.txt",
    "apply": "edit_apply.txt",
}


def help(path: str = "") -> str:
    """Return the committed Rust CLI help snapshot for an edit command."""
    filename = _HELP_FILES.get(path.strip())
    return (
        files("varde_code").joinpath("help", filename).read_text(encoding="utf-8")
        if filename
        else ""
    )


def run(argv: Sequence[str], io=None) -> int:
    """Run AST edit with the same proposal-store resolution as the Rust app."""
    args = list(argv)
    if args and args[0].startswith("varde"):
        args.pop(0)
    if args and args[0] == "edit":
        args.pop(0)
    if not args:
        print(help("preview"), end="")
        return 0
    has_subcommand_help = (
        len(args) >= 2
        and args[0] in {"preview", "apply"}
        and any(item in {"--help", "-h"} for item in args[1:])
    )
    if has_subcommand_help:
        print(help(args[0]), end="")
        return 0

    repository_root = Path.cwd().resolve()
    try:
        store_dir = _proposal_store_dir(repository_root)
    except (OSError, ValueError) as error:
        return _resolution_error(args, "working_store_resolution_failed", str(error))
    return run_ast_edit(args, io, Options(repository_root, store_dir))


def _proposal_store_dir(repository_root: Path) -> Path:
    config = varde_config_dir() / "config.toml"
    if not config.exists():
        config = config.with_name("paths.toml")
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    document = tomllib.loads(text)

    root = _repository_memory_root(repository_root)
    projects = document.get("project", {})
    project = next(
        (
            value
            for key, value in projects.items()
            if _canonical(Path(key)) == root and isinstance(value, dict)
        ),
        {},
    )
    defaults = document.get("default", {})
    working = os.environ.get("VARDE_WORKING_DIR")
    if working:
        return _expand(root, working) / "ast-edit"
    if isinstance(project.get("working"), str):
        return _expand(root, project["working"]) / "ast-edit"
    if isinstance(defaults, dict) and isinstance(defaults.get("working"), str):
        return _expand(root, defaults["working"]) / "ast-edit"
    return varde_config_dir() / "ast-edit"


def _repository_memory_root(root: Path) -> Path:
    root = _canonical(root)
    common = _git_path(root, "--git-common-dir")
    git_dir = _git_path(root, "--git-dir")
    if common is None or git_dir is None or common == git_dir:
        return root
    try:
        result = subprocess.run(  # noqa: S603 - Runs git with constructed repository arguments.
            [  # noqa: S607 - Uses the system git executable from PATH.
                "git",
                "--git-dir",
                str(common),
                "config",
                "--null",
                "--get",
                "core.worktree",
            ],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        result = None
    if result and result.returncode == 0:
        raw = result.stdout.removesuffix(b"\0").decode(errors="surrogateescape")
        if raw:
            path = Path(raw)
            return _canonical(path if path.is_absolute() else common / path)
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain", "-z"],  # noqa: S607 - Uses the system git executable from PATH.
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return root
    first = result.stdout.split(b"\0", 1)[0]
    if result.returncode != 0 or not first.startswith(b"worktree "):
        return root
    return _canonical(Path(first[9:].decode(errors="surrogateescape")))


def _git_path(root: Path, flag: str) -> Path | None:
    try:
        result = subprocess.run(  # noqa: S603 - Runs git with constructed repository arguments.
            ["git", "rev-parse", flag],  # noqa: S607 - Uses the system git executable from PATH.
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    return _canonical(path if path.is_absolute() else root / path)


def _canonical(path: Path) -> Path:
    return path.resolve(strict=False)


def _expand(root: Path, value: str) -> Path:
    value = value.replace("{project}", root.name)
    if value == "~" or value.startswith("~/"):
        value = str(Path.home() / value.lstrip("~/"))
    path = Path(value)
    return _canonical(path if path.is_absolute() else root / path)


def _resolution_error(args: list[str], code: str, message: str) -> int:
    import json
    import sys

    from varde_core.envelope import tool_error

    if "--json" in args:
        print(
            json.dumps(
                tool_error(code, f"cannot resolve proposal working store: {message}"),
                separators=(",", ":"),
            )
        )
    else:
        print(
            f"varde edit: cannot resolve proposal working store: {message}",
            file=sys.stderr,
        )
    return 1
