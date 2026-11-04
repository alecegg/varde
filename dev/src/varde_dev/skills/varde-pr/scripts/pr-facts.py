#!/usr/bin/env python3
"""Collect commit, file, and indexed impact facts for a pull request range."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

FILE_LIMIT = 10
SYMBOL_LIMIT = 10
PUBLIC_KINDS = {"function", "class", "method", "interface", "struct", "enum"}


def run(
    command: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603 - Runs the assembled GitHub CLI or Git query command.


def git(root: Path, *args: str) -> str:
    result = run(["git", "-C", str(root), *args])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def query_varde(
    args: list[str], payload: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    command = ["varde", *args]
    if payload is not None:
        command.extend(["--json", json.dumps(payload)])
    try:
        result = run(command)
    except FileNotFoundError:
        return None, "varde is not available on PATH"
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        message = (
            result.stderr.strip() or result.stdout.strip() or "varde returned no JSON"
        )
        return None, message
    if (
        result.returncode
        or not isinstance(envelope, dict)
        or envelope.get("ok") is not True
    ):
        data = envelope.get("data", {}) if isinstance(envelope, dict) else {}
        error = data.get("error", {}) if isinstance(data, dict) else {}
        message = error.get("message") or result.stderr.strip() or "varde query failed"
        code = error.get("code")
        return envelope if isinstance(
            envelope, dict
        ) else None, f"{code}: {message}" if code else message
    return envelope, None


def baseline_index(
    root: Path, revision: str
) -> tuple[tempfile.TemporaryDirectory[str] | None, str | None, str | None]:
    scratch = tempfile.TemporaryDirectory(prefix=".varde-pr-", dir=root)
    source = Path(scratch.name) / "base"
    source.mkdir()
    archive = subprocess.Popen(  # noqa: S603 - Streams a controlled Git archive command for the requested revision.
        ["git", "-C", str(root), "archive", revision],  # noqa: S607 - Git is resolved from PATH as the repository tool.
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if archive.stdout is None:
            raise RuntimeError("git archive stdout pipe was not created")
        with tarfile.open(fileobj=archive.stdout, mode="r|*") as bundle:
            bundle.extractall(source, filter="data")
    except (OSError, tarfile.TarError) as error:
        archive.kill()
        archive.wait()
        scratch.cleanup()
        return None, None, f"could not materialize base revision: {error}"
    stderr = archive.stderr.read().decode().strip() if archive.stderr else ""
    if archive.wait():
        scratch.cleanup()
        return None, None, stderr or "could not read base revision"
    envelope, error = query_varde(["map", "build", "--repo-root", str(source)])
    if error:
        scratch.cleanup()
        return None, None, error
    data = envelope.get("data", {}) if envelope else {}
    db_path = data.get("dbPath") if isinstance(data, dict) else None
    if not isinstance(db_path, str):
        scratch.cleanup()
        return None, None, "index build returned no dbPath"
    return scratch, db_path, None


def result_data(envelope: dict[str, Any] | None) -> Any:
    return envelope.get("data") if envelope else None


def changed_symbols(data: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(data, list):
        return []
    symbols: list[tuple[str, dict[str, Any]]] = []
    for file_change in data:
        if not isinstance(file_change, dict) or not isinstance(
            file_change.get("symbols"), list
        ):
            continue
        path = file_change.get("file")
        if not isinstance(path, str):
            continue
        symbols.extend(
            (path, symbol)
            for symbol in file_change["symbols"]
            if isinstance(symbol, dict) and symbol.get("kind") in PUBLIC_KINDS
        )
    return symbols


def gather_impact(
    root: Path, paths: list[str], symbols: list[tuple[str, dict[str, Any]]]
) -> tuple[list[Any], list[Any], list[str]]:
    file_results = []
    symbol_results = []
    errors = []
    for path in paths[:FILE_LIMIT]:
        envelope, error = query_varde(
            ["map", "blast_radius"],
            {"repoRoot": str(root), "filePath": path, "resultsLimit": FILE_LIMIT},
        )
        if error:
            errors.append(f"blast_radius {path}: {error}")
        else:
            file_results.append({"file": path, "result": result_data(envelope)})
    for path, symbol in symbols[:SYMBOL_LIMIT]:
        envelope, error = query_varde(
            ["map", "symbol_blast_radius"],
            {
                "repoRoot": str(root),
                "filePath": path,
                "name": symbol["name"],
                "kind": symbol["kind"],
                "resultsLimit": FILE_LIMIT,
            },
        )
        if error:
            errors.append(f"symbol_blast_radius {path}:{symbol['name']}: {error}")
        else:
            symbol_results.append(
                {"file": path, "symbol": symbol, "result": result_data(envelope)}
            )
    return file_results, symbol_results, errors


def collect(root: Path, base: str, head: str) -> dict[str, Any]:
    merge_base = git(root, "merge-base", base, head).strip()
    head_oid = git(root, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    checked_out = git(root, "rev-parse", "HEAD").strip()
    if head_oid != checked_out:
        raise RuntimeError(
            f"head {head} is not checked out; check it out before collecting "
            "range impact"
        )
    range_spec = f"{base}...{head}"
    head_range = f"{merge_base}..{head}"
    commits = git(root, "log", "--format=%H %s", head_range).splitlines()
    paths = [
        path
        for path in git(
            root, "diff", "--name-only", "--find-renames", range_spec
        ).splitlines()
        if path
    ]
    diff_stat = git(root, "diff", "--stat", "--find-renames", range_spec).strip()
    facts: dict[str, Any] = {
        "range": range_spec,
        "mergeBase": merge_base,
        "commits": commits,
        "files": paths,
        "diffStat": diff_stat,
        "detectChanges": None,
        "blastRadius": [],
        "symbolBlastRadius": [],
        "truncated": False,
        "truncatedDetails": {"files": False, "symbols": False},
    }
    scratch, db_path, build_error = baseline_index(root, merge_base)
    if build_error:
        facts["blastRadiusNote"] = not_measured(build_error)
        facts["blastRadiusError"] = build_error
        return facts
    try:
        envelope, error = query_varde(
            ["map", "detect_changes"],
            {
                "repoRoot": str(root),
                "dbPath": db_path,
                "diffMode": "range",
                "range": head_range,
            },
        )
        facts["detectChanges"] = envelope
        if error:
            facts["blastRadiusNote"] = not_measured(error)
            facts["blastRadiusError"] = error
            return facts
        symbols = changed_symbols(result_data(envelope))
        facts["truncatedDetails"]["files"] = len(paths) > FILE_LIMIT
        facts["truncatedDetails"]["symbols"] = len(symbols) > SYMBOL_LIMIT
        facts["truncated"] = any(facts["truncatedDetails"].values())
        facts["changedPublicSymbolsCount"] = len(symbols)
        file_results, symbol_results, errors = gather_impact(root, paths, symbols)
        facts["blastRadius"] = file_results
        facts["symbolBlastRadius"] = symbol_results
        if errors:
            facts["blastRadiusNote"] = not_measured(errors[0])
            facts["blastRadiusError"] = errors
        return facts
    finally:
        if scratch:
            scratch.cleanup()


def not_measured(error: str) -> str:
    if "index_missing" in error:
        return "blast radius not measured: no index"
    return f"blast radius not measured: {error}"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: pr-facts.sh <base> <head>", file=sys.stderr)
        return 2
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        print(json.dumps(collect(root, argv[1], argv[2]), indent=2))
    except (OSError, RuntimeError) as error:
        message = str(error)
        print(
            json.dumps(
                {
                    "blastRadius": [],
                    "blastRadiusNote": not_measured(message),
                    "blastRadiusError": message,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
