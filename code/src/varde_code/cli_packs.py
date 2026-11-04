"""CLI for ``varde map packs``: build and check committed context packs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from varde_code.errors import ApiError
from varde_code.packs import README
from varde_code.packs.gitinfo import toplevel

_HELP_DIR = Path(__file__).with_name("help")
_HELP_FILES = {
    "map packs": "map_packs.txt",
    "map packs build": "map_packs_build.txt",
    "map packs status": "map_packs_status.txt",
}
README_MAX_BEHIND = 100
_MISSING = "packs missing; run varde map packs build"
_LINKED_WORKTREE = (
    "linked worktree has no index; run varde map packs build from the main checkout"
)


def _is_linked_worktree(root: Path) -> bool:
    return (root / ".git").is_file()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="varde map packs", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", add_help=False)
    build.add_argument("folder", nargs="?")
    build.add_argument("--repo-root")
    build.add_argument("--all", action="store_true")
    build.add_argument("--stale", action="store_true")
    build.add_argument("--readme-max-behind", type=int, default=README_MAX_BEHIND)
    status = commands.add_parser("status", add_help=False)
    status.add_argument("--repo-root")
    status.add_argument("--json", action="store_true")
    status.add_argument("--check", action="store_true")
    status.add_argument("--readme-max-behind", type=int, default=README_MAX_BEHIND)
    return parser


def help(path: str = "map packs") -> str:
    """Return the committed help text for a ``map packs`` path."""
    return (_HELP_DIR / _HELP_FILES[path.strip()]).read_text(encoding="utf-8")


def _root(value: str | None) -> Path:
    return toplevel(Path(value or Path.cwd()).resolve())


def _extractor(io: object):
    from varde_code.extract.provider import CodeExtractionProvider

    return getattr(io, "extractor", None) or CodeExtractionProvider()


def _build_paths(args: argparse.Namespace, root: Path, io: object) -> list[Path]:
    if args.all:
        from varde_code.packs.refresh import build_all

        return build_all(root, _extractor(io))
    if args.stale:
        from varde_code.packs.refresh import build_stale

        return build_stale(root, _extractor(io), args.readme_max_behind)
    if args.folder is None:
        from varde_code.packs.repo_map import build

        return [build(root, _extractor(io))]
    from varde_code.packs.module_pack import build as build_module

    return [build_module(root, args.folder, _extractor(io))]


def _run_build(args: argparse.Namespace, io: object) -> int:
    root = _root(args.repo_root)
    if _is_linked_worktree(root):
        print(_LINKED_WORKTREE, file=sys.stderr)
        return 1
    batch = args.all or args.stale
    if args.all and args.stale or batch and args.folder is not None:
        print(
            "error: --all and --stale take no folder and exclude each other",
            file=sys.stderr,
        )
        return 2
    try:
        written = _build_paths(args, root, io)
    except ApiError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        single = not batch and error.code == "folder_not_found"
        return 1 if single else 2
    for path in written:
        print(f"wrote {path.relative_to(root).as_posix()}")
    if args.stale and not written:
        print("packs fresh")
    return 0


def _print_status(report: dict[str, object]) -> None:
    packs = report["packs"]
    for pack in packs if isinstance(packs, list) else []:
        state = "stale" if pack["stale"] else "fresh"
        print(
            f"{pack['path']}: {state} ({pack['commits_behind']} commits behind, "
            f"commit {pack['commit']}, scope {pack['scope']})"
        )
    index = report["index"]
    print(f"index: {json.dumps(index, sort_keys=True)}")


def _listed(root: Path) -> set[str] | None:
    from varde_code.packs.refresh import MODULES_FILE, module_path, read_modules

    if not (root / MODULES_FILE).is_file():
        return None
    return {module_path(folder) for folder in read_modules(root)}


def _run_status(args: argparse.Namespace) -> int:
    from varde_code.packs.status import collect_packs, index_status

    root = _root(args.repo_root)
    try:
        packs = collect_packs(root, _listed(root), args.readme_max_behind)
    except ApiError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 2
    report = {"packs": [asdict(pack) for pack in packs], "index": index_status(root)}
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        _print_status(report)
    if not args.check:
        return 0
    if not (root / README).is_file():
        print(_MISSING, file=sys.stderr)
        return 1
    return 1 if any(pack.stale for pack in packs) else 0


def run(argv: Sequence[str], io: object = None) -> int:
    """Run ``map packs`` commands; ``argv`` starts at the ``map`` token."""
    args = list(argv)
    if args[:1] == ["map"]:
        args.pop(0)
    args = args[1:] if args[:1] == ["packs"] else args
    if not args or args[0] in {"--help", "-h"}:
        print(help("map packs"), end="")
        return 0
    if args[0] in {"build", "status"} and set(args[1:]) & {"--help", "-h"}:
        print(help(f"map packs {args[0]}"), end="")
        return 0
    try:
        parsed = _parser().parse_args(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if parsed.command == "build":
        return _run_build(parsed, io)
    return _run_status(parsed)
