"""Export existing resolver edges from an isolated temporary code index.

The existing index does not persist resolver-pass attribution, so every edge
uses ``pass: local``. It also does not distinguish external calls from other
unresolved calls; those remain ``opaque``. The returned JSONL file is a caller-
owned temporary artifact and should be removed when it is no longer needed.
Each row includes ``file``, the call site's repo-relative path as stored in the
index, and ``name``, the call entity's name. Together these let audit records
join by repository, file, line, and, for multiple calls on one line, name.
Resolved rows also carry the callee identity read from the index: ``callee``
(the temporary numeric entity id, for debugging), ``callee_file`` (repo-relative
path), ``callee_name`` (declared entity name) and ``callee_line`` (entity start
line). Audits compare ``callee_file``/``callee_name``/``callee_line`` with the
ground-truth target key instead of the index-local numeric id.
"""

from __future__ import annotations

import json
import os
import pwd
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from varde_code.model import EdgeKind, EntityKind


def export_edges(repo_path: str | Path, timeout_seconds: float | None = None) -> Path:
    """Build an isolated index for ``repo_path`` and return ``edges.jsonl``."""
    repo = Path(repo_path).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="varde-existing-index-") as scratch:
        scratch_path = Path(scratch)
        env = os.environ.copy()
        env["VARDE_TREE_SITTER_CACHE_DIR"] = _grammar_cache_dir(env)
        for variable in (
            "HOME",
            "XDG_CONFIG_HOME",
            "VARDE_CONFIG_DIR",
            "XDG_DATA_HOME",
        ):
            directory = scratch_path / variable.lower()
            directory.mkdir()
            env[variable] = str(directory)
        script = (
            "from varde_code.extract.provider import CodeExtractionProvider; "
            "from varde_code.index.build import build; "
            f"print(build({str(repo)!r}, CodeExtractionProvider()).db_path)"
        )
        completed = subprocess.run(  # noqa: S603 - Runs the repository's language adapter to export benchmark data.
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"isolated index build failed for {repo} "
                f"(exit {completed.returncode}); inner stderr tail:\n"
                f"{completed.stderr[-4096:]}"
            )
        output = _new_output_path()
        with sqlite3.connect(completed.stdout.strip()) as connection:
            edges = _read_call_edges(connection, repo)
        with output.open("w", encoding="utf-8") as stream:
            for edge in edges:
                stream.write(json.dumps(edge, sort_keys=True) + "\n")
    return output


def _grammar_cache_dir(env: dict[str, str]) -> str:
    configured = env.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        return configured
    cache_env = env.copy()
    cache_env["HOME"] = pwd.getpwuid(os.getuid()).pw_dir
    cache_env.pop("VARDE_TREE_SITTER_CACHE_DIR", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tree_sitter_language_pack import cache_dir; print(cache_dir())",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=cache_env,
    )
    return completed.stdout.strip()


def _new_output_path() -> Path:
    descriptor, name = tempfile.mkstemp(prefix="edges-", suffix=".jsonl")
    os.close(descriptor)
    return Path(name)


def _read_call_edges(
    connection: sqlite3.Connection, repo_path: Path
) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    entities = connection.execute(
        "SELECT id, kind, file_id, name, start_line, end_line, enclosing_function "
        "FROM entities ORDER BY id"
    ).fetchall()
    files = {
        row["id"]: row["path"]
        for row in connection.execute("SELECT id, path FROM files")
    }
    functions_by_file_and_name: dict[tuple[int, str], list[sqlite3.Row]] = defaultdict(
        list
    )
    for entity in entities:
        if entity["kind"] in (EntityKind.FUNCTION, EntityKind.CALLABLE_BOUNDARY):
            functions_by_file_and_name[(entity["file_id"], entity["name"])].append(
                entity
            )

    entities_by_id = {entity["id"]: entity for entity in entities}
    edges = connection.execute(
        "SELECT from_entity_id, to_entity_id, resolved "
        "FROM resolved_edges WHERE kind = ? ORDER BY id",
        (EdgeKind.CALL.as_i64(),),
    ).fetchall()
    result = []
    for edge in edges:
        call = entities_by_id.get(edge["from_entity_id"])
        if call is None:
            continue
        candidates = _caller_candidates(call, functions_by_file_and_name)
        caller, caller_candidates = _caller_id(call, candidates, files)
        callee = (
            _callee_function(
                edge["to_entity_id"], entities_by_id, functions_by_file_and_name
            )
            if edge["resolved"]
            else None
        )
        resolved = callee is not None
        row: dict[str, Any] = {
            "caller": caller,
            "file": _repo_relative(files, call["file_id"], repo_path),
            "name": call["name"],
            "site_line": call["start_line"],
            "callee": str(callee["id"]) if callee is not None else None,
            "kind": "resolved" if resolved else "opaque",
            "pass": "local",
        }
        if callee is not None:
            row["callee_file"] = _repo_relative(files, callee["file_id"], repo_path)
            row["callee_name"] = callee["name"]
            row["callee_line"] = callee["start_line"]
        if caller_candidates:
            row["caller_candidates"] = caller_candidates
        result.append(row)
    return result


def _repo_relative(files: dict[int, str], file_id: int, repo_path: Path) -> str:
    return Path(files[file_id]).relative_to(repo_path).as_posix()


def _callee_function(
    target_id: int | None,
    entities_by_id: dict[int, sqlite3.Row],
    functions_by_file_and_name: dict[tuple[int, str], list[sqlite3.Row]],
) -> sqlite3.Row | None:
    target = entities_by_id.get(target_id)
    if target is None:
        return None
    if target["kind"] in (EntityKind.FUNCTION, EntityKind.CALLABLE_BOUNDARY):
        return target
    candidates = functions_by_file_and_name.get((target["file_id"], target["name"]), [])
    if len(candidates) == 1:
        return candidates[0]
    return None


def _caller_candidates(
    call: sqlite3.Row,
    functions_by_file_and_name: dict[tuple[int, str], list[sqlite3.Row]],
) -> list[str]:
    name = call["enclosing_function"]
    if not name:
        return []
    matches = functions_by_file_and_name.get((call["file_id"], name), [])
    containing = [
        function
        for function in matches
        if function["start_line"] <= call["start_line"] <= function["end_line"]
    ]
    selected = containing or matches
    return sorted(str(function["id"]) for function in selected)


def _caller_id(
    call: sqlite3.Row, candidates: list[str], files: dict[int, str]
) -> tuple[str, list[str]]:
    if not call["enclosing_function"]:
        return f"module:{files[call['file_id']]}", []
    if len(candidates) == 1:
        return candidates[0], []
    return "ambiguous", candidates
