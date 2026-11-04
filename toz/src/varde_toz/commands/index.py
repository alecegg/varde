"""`index` command."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from varde_toz.capture import CaptureResult
from varde_toz.config import env_os
from varde_toz.index_files import (
    collect_paths,
    index_bytes,
    index_file,
    skipped_index_message,
)
from varde_toz.project import project_root

HELP = """Index local files or directories so they can be searched (records mtime + hash)

Usage: varde run index [OPTIONS] <PATHS>...

Arguments:
  <PATHS>...  Files or directories; `-` reads stdin

Options:
      --fallback-dir <FALLBACK_DIR>  External store to try after primary-store access fails
  -l, --label <LABEL>                Human label (single path only; also the supersession key)
      --project <PROJECT>            Project directory (default: git root of cwd, else cwd)
  -r, --recursive                    Descend into subdirectories
  -g, --glob <GLOB>                  Only files whose name matches this glob (e.g. "*.md", "*.{rs,toml}")
      --json                         Machine-readable JSON output
      --quiet                        Print only the handle line on overflow
  -h, --help                         Print help
"""


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(HELP, end="")
        return 0
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("-l", "--label")
    parser.add_argument("-r", "--recursive", action="store_true")
    parser.add_argument("-g", "--glob")
    parser.add_argument("--fallback-dir")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    root = Path(args.project).resolve() if args.project else project_root()
    json_output = args.json or env_os("TOZ_JSON") not in (None, "", "0", "false")
    quiet = args.quiet or env_os("TOZ_QUIET") not in (None, "", "0", "false")
    if args.paths == ["-"]:
        result = index_bytes(sys.stdin.buffer.read(), args.label, root)
        return _emit(result, json_output, quiet, args.label or "stdin", root)
    try:
        files = collect_paths(
            [Path(path) for path in args.paths], args.recursive, args.glob
        )
    except (OSError, ValueError, re.error) as exc:
        print(f"varde-toz: {exc}", file=sys.stderr)
        return 2
    label = args.label if len(files) == 1 else None
    if len(files) > 1 and args.label:
        print("varde-toz: --label ignored for multiple files")
    worst = 0
    for path in files:
        try:
            result = index_file(path, label, root)
            worst = max(worst, _emit(result, json_output, quiet, str(path), root))
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"varde-toz: {path}: {exc}")
            worst = 1
    return worst


def _emit(
    result: CaptureResult, json_output: bool, quiet: bool, source: str, root: Path
) -> int:
    if result.skip_reason:
        print(skipped_index_message(source, result.skip_reason, root), end="")
        return 1
    if result.status:
        if json_output:
            print(
                json.dumps(
                    {"preview": result.output},
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
        elif quiet:
            lines = result.output.splitlines()
            print(lines[0] if lines else "")
        else:
            print(result.output, end="")
    return 0
