"""Remove or age-prune Toz stores."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import NoReturn

from varde_toz.config import config_dir
from varde_toz.project import project_key
from varde_toz.store import Store

from ._maintenance import (
    all_stores,
    current_project,
    current_store,
    error,
    json_enabled,
)


def _raise_validation(error: Exception) -> NoReturn:
    raise error


HELP = (
    "Delete this project's store (or prune with --older-than)\n\n"
    "Usage: varde run purge [OPTIONS]\n\n"
    "Options:\n"
    "      --fallback-dir <FALLBACK_DIR>  External store to try after "
    "primary-store access fails\n"
    "  -y, --yes                          Skip the confirmation prompt "
    "(required when stdin is not a terminal)\n"
    "      --global                       Every project store (and the fetch cache)\n"
    "      --project <PROJECT>            Project directory (default: "
    "git root of cwd, else cwd)\n"
    "      --json                         Machine-readable JSON output\n"
    "      --older-than <OLDER_THAN>      Prune captures older than this "
    "(e.g. 30m, 12h, 7d) instead of wiping\n"
    "      --quiet                        Print only the handle line on overflow\n"
    "  -h, --help                         Print help\n"
)

_SQLITE_INT_MAX = (1 << 63) - 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback-dir")
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("--global", action="store_true", dest="global_purge")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--older-than")
    parser.add_argument("--quiet", action="store_true")
    return parser


def _duration(value: str) -> int:
    text = value.strip()
    index = next(
        (i for i, char in enumerate(text) if not char.isascii() or not char.isdigit()),
        len(text),
    )
    number, unit = text[:index], text[index:].strip()
    try:
        amount = int(number)
    except ValueError as exc:
        raise ValueError(f"invalid duration {text!r}") from exc
    if amount > _SQLITE_INT_MAX:
        raise ValueError(
            f"invalid duration {json.dumps(text)}: number too large to fit "
            "in target type"
        )
    factors = {
        "": 1,
        "s": 1,
        "sec": 1,
        "secs": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "h": 3600,
        "hr": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
        "w": 604800,
        "week": 604800,
        "weeks": 604800,
    }
    if unit not in factors:
        raise ValueError(f"invalid duration {text!r} (use e.g. 30m, 12h, 7d)")
    seconds = amount * factors[unit]
    if seconds > _SQLITE_INT_MAX:
        raise ValueError(
            f"invalid duration {json.dumps(text)}: number too large to fit "
            "in target type"
        )
    return seconds


def _cache_dir() -> Path:
    return config_dir() / "cache"


def _cache_has_entries() -> bool:
    try:
        return next(_cache_dir().iterdir(), None) is not None
    except FileNotFoundError:
        return False


def _clear_cache() -> int:
    directory = _cache_dir()
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return 0
    removed = 0
    for path in entries:
        if path.suffix not in (".meta", ".body"):
            continue
        if path.suffix == ".meta":
            removed += 1
        path.unlink()
    return removed


def _confirm(yes: bool, prompt: str) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise ValueError("refusing without --yes (stdin is not a terminal)")
    print(f"varde-toz: {prompt}? [y/N] ", end="", file=sys.stderr, flush=True)
    return input().strip() in ("y", "Y", "yes")


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if "--help" in values or "-h" in values:
        print(HELP, end="")
        return 0
    try:
        args = _parser().parse_args(values)
        if args.fallback_dir and os.environ.get("TOZ_FALLBACK_DIR") is None:
            os.environ["TOZ_FALLBACK_DIR"] = args.fallback_dir
        root = current_project(args.project)
        targets = (
            all_stores(root)
            if args.global_purge
            else [(project_key(root), current_store(root))]
        )
        targets = [(key, path) for key, path in targets if path.exists()]
        cached = args.global_purge and args.older_than is None and _cache_has_entries()
        if not targets and not cached:
            print("varde-toz: nothing to purge")
            return 0
        if args.older_than is not None:
            seconds = _duration(args.older_than)
            cutoff = int(time.time()) - seconds
            if cutoff < -(1 << 63):
                _raise_validation(
                    ValueError(
                        f"invalid duration {json.dumps(args.older_than)}: "
                        "number too large to fit in target type"
                    )
                )
            total = 0
            for key, path in targets:
                with Store.open(path) as store:
                    cursor = store.conn.execute(
                        "DELETE FROM captures WHERE created_at <= ? "
                        "AND state != 'running'",
                        (cutoff,),
                    )
                    removed = cursor.rowcount
                    store.conn.commit()
                    store.vacuum()
                total += removed
                if args.global_purge:
                    print(f"{key}: removed {removed} capture(s)")
            if json_enabled(args):
                print(json.dumps({"removed": total}, separators=(",", ":")))
            else:
                print(
                    f"varde-toz: removed {total} capture(s) older than "
                    f"{args.older_than}"
                )
            return 0
        prompt = (
            f"delete ALL {len(targets)} Toz store(s) and cached pages"
            if args.global_purge
            else f"delete the Toz store for {project_key(root)}"
        )
        if not _confirm(args.yes, prompt):
            print("varde-toz: aborted")
            return 1
        removed = 0
        for key, path in targets:
            shutil.rmtree(path.parent)
            removed += 1
            if not json_enabled(args):
                print(f"removed {key}")
        if args.global_purge:
            swept = _clear_cache()
            if not json_enabled(args):
                print(f"removed {swept} cached page(s)")
        if json_enabled(args):
            print(json.dumps({"removed_stores": removed}, separators=(",", ":")))
    except (OSError, ValueError, sqlite3.Error) as exc:
        return error(str(exc))
    else:
        return 0
