"""CLI commands for building, pruning, and watching the code index."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import NoReturn

from varde_core.paths import varde_config_dir

from varde_code.seams import ExtractionProvider

_HELP_DIR = Path(__file__).with_name("help")
_extraction_provider: ExtractionProvider | None = None


def register_extraction_provider(provider: ExtractionProvider) -> None:
    """Register the process extraction provider used when no IO object is passed."""
    global _extraction_provider  # noqa: PLW0603 - updates configured provider state
    _extraction_provider = provider


def _provider(io: object) -> ExtractionProvider | None:
    provider = getattr(io, "extractor", None)
    return _extraction_provider if provider is None else provider


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="varde")
    commands = parser.add_subparsers(dest="group", required=True)
    map_parser = commands.add_parser("map")
    map_commands = map_parser.add_subparsers(dest="command", required=True)
    build = map_commands.add_parser("build")
    build.add_argument("--repo-root", required=True)
    build.add_argument("--force", action="store_true")
    build.add_argument("--changed-files", action="store_true")
    prune = map_commands.add_parser("prune")
    prune.add_argument("--json", required=True)
    setup = commands.add_parser("setup")
    setup_commands = setup.add_subparsers(dest="command", required=True)
    watch = setup_commands.add_parser("watch")
    watch.add_argument("--repo", action="append", default=[])
    watch.add_argument("--config")
    watch.add_argument("--debounce-ms", type=int, default=750)
    watch.add_argument("--list", action="store_true")
    watch.add_argument("--ensure", action="store_true")
    watch.add_argument("--stop", action="store_true")
    watch.add_argument("--remove-index", action="store_true")
    watch.add_argument("--stop-all", action="store_true")
    return parser


def _help(path: str) -> str:
    names = {
        "map build": "map_build.txt",
        "map prune": "map_prune.txt",
        "setup watch": "setup_watch.txt",
    }
    try:
        filename = names[path.strip()]
    except KeyError as exc:
        raise ValueError(f"unknown code help path: {path}") from exc
    return (_HELP_DIR / filename).read_text(encoding="utf-8")


def _result(value: object, stream=None) -> None:
    print(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        file=stream or sys.stdout,
    )


def _build_result(value: object) -> None:
    _result(
        {
            "data": value,
            "meta": {"compact": True, "truncated": False},
            "ok": True,
            "outcome": "success",
            "schema_version": 1,
        }
    )


def _watch_result(data: object = None, *, error: tuple[str, str] | None = None) -> None:
    if error is None:
        value = {
            "schema_version": 1,
            "ok": True,
            "outcome": "success",
            "data": data,
            "meta": {"compact": False, "truncated": False},
        }
    else:
        code, message = error
        value = {
            "schema_version": 1,
            "ok": False,
            "outcome": "tool-error",
            "data": {"error": {"code": code, "message": message}},
            "meta": {"compact": False, "truncated": False},
        }
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _resolve_watch_repos(repos: list[str], config_path: str | None) -> list[Path]:
    config: dict[str, object] = {}
    path = Path(config_path) if config_path else None
    if path is None and not repos:
        default_path = varde_config_dir() / "code" / "watch.toml"
        path = default_path if default_path.exists() else None
    if path is not None:
        try:
            with path.open("rb") as stream:
                config = tomllib.load(stream)
        except OSError as error:
            raise ValueError(f"reading watch config {path}") from error
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"parsing watch config {path} as TOML: {error}") from error

    configured_repos = config.get("repos", [])
    if not isinstance(configured_repos, list) or not all(
        isinstance(repo, str) for repo in configured_repos
    ):
        raise ValueError("watch config repos must be a list of paths")
    candidates = [*repos, *configured_repos]
    parent_dirs = config.get("parent_dirs", [])
    if not isinstance(parent_dirs, list) or not all(
        isinstance(parent, str) for parent in parent_dirs
    ):
        raise ValueError("watch config parent_dirs must be a list of paths")
    for parent in parent_dirs:
        try:
            candidates.extend(
                str(child)
                for child in Path(parent).iterdir()
                if (child / ".git").exists()
            )
        except OSError as error:
            raise ValueError(f"reading parent dir {parent}: {error}") from error
    resolved: list[Path] = []
    for value in candidates:
        try:
            repo = Path(value).resolve(strict=True)
        except OSError as error:
            raise ValueError(f"resolving watch path {value}: {error}") from error
        if not (repo / ".git").exists():
            raise ValueError(f"{repo} is not a git repo root (no .git entry)")
        if repo not in resolved:
            resolved.append(repo)
    if not resolved:
        raise ValueError(
            "no repos to watch: pass --repo or configure repos/parent_dirs"
        )
    return resolved


def _run_watch_action(args: argparse.Namespace) -> int:
    from varde_code.index import supervise

    if args.list:
        _watch_result(supervise.list_instances())
        return 0
    if args.stop_all:
        _watch_result(supervise.stop_all())
        return 0
    if args.remove_index and not args.stop:
        _watch_result(error=("invalid_input", "--remove-index requires --stop"))
        return 1
    if (
        args.stop
        and args.remove_index
        and (args.config is not None or len(args.repo) != 1)
    ):
        _watch_result(
            error=(
                "invalid_input",
                "--stop --remove-index requires exactly one --repo and no --config",
            )
        )
        return 1
    try:
        repos = _resolve_watch_repos(args.repo, args.config)
        if args.stop and args.remove_index:
            watcher, removed = supervise.stop_and_remove_index(repos[0])
            _watch_result({"watcher": watcher, "indexRemoved": removed})
        elif args.stop:
            _watch_result(supervise.stop(repos))
        else:
            _watch_result(error=("invalid_input", "watch action is not supported"))
            return 1
    except (OSError, RuntimeError, ValueError) as error:
        code = "invalid_input" if isinstance(error, ValueError) else "watch_error"
        _watch_result(error=(code, str(error)))
        return 1
    else:
        return 0


def _run_build(args: argparse.Namespace, io: object) -> int:
    from varde_code.index.build import build
    from varde_code.index.incremental import refresh

    extractor = _provider(io)
    if extractor is None:
        raise RuntimeError("code index build requires an extraction provider")
    root = Path(args.repo_root)
    if not args.force and (root.exists() and _index_exists(root)):
        summary = refresh(root, extractor)
    else:
        summary = build(root, extractor)
    changed_files = [_relative_build_path(path, root) for path in summary.changed_files]
    data: dict[str, object] = (
        {"changedFiles": changed_files} if args.changed_files else {}
    )
    data.update(
        {
            "changedFilesCount": len(changed_files),
            "changedFilesSample": changed_files[:10],
            "dbPath": summary.db_path,
            "diagnostics": summary.diagnostics,
            "entities": summary.entities,
            "reparsed": getattr(summary, "reparsed", len(summary.changed_files)),
            "symbols": summary.symbols,
            "unchanged": getattr(summary, "unchanged", 0),
        }
    )
    _build_result(data)
    return 0


def _relative_build_path(path: str, root: Path) -> str:
    if path.startswith("<ROOT>/"):
        return path[len("<ROOT>/") :]
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def _index_exists(root: Path) -> bool:
    from varde_code.index.paths import repo_db_path

    return repo_db_path(root).is_file()


def _run_prune(args: argparse.Namespace) -> int:
    from varde_code.index.prune import run

    try:
        value = json.loads(args.json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid --json: {exc.msg}") from exc
    _result(run(value))
    return 0


def _run_watch(args: argparse.Namespace, io: object) -> int:
    if args.list or (
        not args.ensure and (args.stop or args.remove_index or args.stop_all)
    ):
        return _run_watch_action(args)
    from varde_code.index.slice import IndexService

    repos: list[str] = [str(repo) for repo in args.repo]
    if not repos:
        if args.config is not None:
            # Foreground watch resolves configured paths through the same path as stop.
            repos = [str(repo) for repo in _resolve_watch_repos([], args.config)]
        else:
            raise ValueError("setup watch requires at least one --repo")
    if args.ensure:
        from varde_code.index.supervise import ensure

        paths = [str(ensure(repo)) for repo in repos]
        _result({"ensured": paths})
        return 0
    provider = _provider(io)
    if provider is None:
        raise RuntimeError("code index watch requires an extraction provider")
    from varde_code.index.watch import run_foreground

    run_foreground(
        tuple(repos), IndexService(provider), debounce=args.debounce_ms / 1000
    )
    return 0


class CodeIndexModule:
    name = "code"

    def run(self, argv: list[str], io: object = None) -> int:
        try:
            args = _parser().parse_args(argv)
            if args.group == "map" and args.command == "build":
                return _run_build(args, io)
            if args.group == "map" and args.command == "prune":
                return _run_prune(args)
            if args.group == "setup" and args.command == "watch":
                return _run_watch(args, io)
        except (ValueError, OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 2

    def help(self, path: str = "") -> str:
        return _help(path)


def register() -> CodeIndexModule:
    return CodeIndexModule()


__all__ = ["CodeIndexModule", "register"]
