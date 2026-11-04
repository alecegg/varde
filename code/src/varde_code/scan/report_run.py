"""Run the scan report: scan, build the index once if needed, print the summary."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from varde_code.packs.gitinfo import toplevel
from varde_code.packs.warnings import collect_pack_warnings
from varde_code.query.output import render
from varde_code.query.params import QueryError
from varde_code.scan.report import ReportError, index_error_code, summary_line

Scan = Callable[[dict], dict]
Build = Callable[[Path], None]


def default_scan(payload: dict) -> dict:
    """Run the in-process scan and return its response envelope."""
    from varde_code.scan.core import scan_repo

    try:
        return render(scan_repo({**payload, "skipQuality": True}), payload)
    except QueryError as error:
        return render(None, error=(error.code, str(error)))


def default_build(root: Path) -> None:
    """Build or refresh the repo index in process."""
    from varde_code.extract.provider import CodeExtractionProvider
    from varde_code.packs.index_refresh import ensure_index

    ensure_index(root, CodeExtractionProvider())


def default_root() -> Path:
    """Git top level of the current directory."""
    return toplevel(Path.cwd())


def _timed_scan(scan: Scan, payload: dict) -> tuple[dict, int]:
    started = time.monotonic()
    result = scan(payload)
    return result, int(time.monotonic() - started)


def _is_varde_repo(root: Path) -> bool:
    return (root / "justfile").is_file() and (root / ".githooks").is_dir()


def run_report(
    root: Path,
    no_build: bool,
    readme_max_behind: int,
    scan: Scan = default_scan,
    build: Build = default_build,
) -> int:
    """Print the one-line scan report for ``root`` and return the exit code."""
    if not root.is_dir():
        print("usage: varde scan --report [--repo-root <dir>]", file=sys.stderr)
        return 2
    if _is_varde_repo(root):
        for warning in collect_pack_warnings(root, readme_max_behind):
            print(f"warning: {warning}", file=sys.stderr)
    payload = {"repoRoot": str(root)}
    result, scan_seconds = _timed_scan(scan, payload)
    build_seconds = 0
    status = index_error_code(result)
    if status and no_build:
        print(f'status={status} recovery="varde map build --repo-root {root}"')
        return 0
    if status:
        started = time.monotonic()
        try:
            build(root)
        except Exception as error:  # noqa: BLE001 - any build failure is reported
            print(error, file=sys.stderr)
            print("scan index build failed", file=sys.stderr)
            return 1
        build_seconds = int(time.monotonic() - started)
        result, retry_seconds = _timed_scan(scan, payload)
        scan_seconds += retry_seconds
    try:
        print(summary_line(result, build_seconds, scan_seconds))
    except ReportError as error:
        print(error, file=sys.stderr)
        print(json.dumps(result), file=sys.stderr)
        return 1
    return 0
