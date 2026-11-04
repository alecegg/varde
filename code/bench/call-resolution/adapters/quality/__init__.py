"""Export call edges using the scan-time quality resolver."""

from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
import warnings
from pathlib import Path

from varde_code.parse import language_for_path
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.extract import import_specs
from varde_code.quality_resolve import edges_for_file, prepare


def export_edges(repo_path: str | Path, timeout_seconds: float | None = None) -> Path:
    """Return an audit-compatible JSONL export for a repository checkout."""
    try:
        return _export_edges(Path(repo_path).resolve(strict=True), timeout_seconds)
    except TimeoutError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"quality edge export failed for {repo_path}: {exc}\n"
            f"{traceback.format_exc()}"
        ) from exc


def _export_edges(repo: Path, timeout_seconds: float | None = None) -> Path:
    deadline = (
        time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    )
    ignored_directories = {
        "node_modules",
        "vendor",
        "target",
        "build",
        "dist",
        "__pycache__",
        ".git",
        "third_party",
    }
    files = []
    for directory, subdirectories, filenames in os.walk(repo):
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if not name.startswith(".") and name not in ignored_directories
        )
        files.extend(
            path
            for name in filenames
            if language_for_path(path := Path(directory) / name) is not None
        )
    files.sort()
    facts_by_file = {}
    for source_path in files:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(
                f"quality edge export exceeded timeout of {timeout_seconds} seconds"
            )
        relative = source_path.relative_to(repo).as_posix()
        try:
            raw = source_path.read_bytes()
            language = language_for_path(source_path)
            facts = extract_facts(raw, language, relative)
            text = raw.decode("utf-8-sig", errors="replace")
            facts["imports"] = import_specs(str(source_path), text, language)
            facts_by_file[relative] = facts
        except Exception as exc:  # noqa: BLE001 - isolate a bad source file.
            warnings.warn(f"quality facts failed for {relative}: {exc}", stacklevel=2)
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(
                f"quality edge export exceeded timeout of {timeout_seconds} seconds"
            )

    if files and not facts_by_file:
        raise RuntimeError(f"quality facts failed for all {len(files)} source files")

    context = prepare(facts_by_file, facts_by_file)
    declarations = _declarations_by_id(facts_by_file)
    output = _new_output_path()
    try:
        with output.open("w", encoding="utf-8") as stream:
            for relative in facts_by_file:
                _check_deadline(deadline, timeout_seconds)
                try:
                    exported = _file_edges(
                        relative, facts_by_file, context, declarations
                    )
                except Exception as exc:  # noqa: BLE001 - isolate a bad source file.
                    warnings.warn(
                        f"quality edge resolution failed for {relative}: {exc}",
                        stacklevel=2,
                    )
                    continue
                _check_deadline(deadline, timeout_seconds)
                for edge in exported:
                    _check_deadline(deadline, timeout_seconds)
                    stream.write(json.dumps(edge, sort_keys=True) + "\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    else:
        return output


# Calls outside any function (module level, field initialisers) are exported
# only for the v1 languages; other languages keep their pre-v1 results.
_UNOWNED_CALL_LANGUAGES = frozenset(
    {"python", "typescript", "javascript", "tsx", "csharp"}
)


def _file_edges(
    path: str, facts_by_file: dict, context: object, declarations: dict
) -> list[dict]:
    facts = facts_by_file[path]
    functions = {function["id"]: function for function in facts.get("functions", ())}
    types = {record["id"]: record for record in facts.get("types", ())}
    calls = facts.get("call_sites", ())
    resolved = edges_for_file(context, path)
    result = []
    keeps_unowned = language_for_path(path) in _UNOWNED_CALL_LANGUAGES
    for call, edge in zip(calls, resolved, strict=True):
        caller = call.get("caller")
        if not isinstance(caller, str) and not keeps_unowned:
            continue
        row = {
            "caller": caller if isinstance(caller, str) else None,
            "file": path,
            "name": call["name"],
            "site_line": call["line"],
            "callee": edge["callee"],
            "kind": edge["kind"],
            "pass": edge["pass"],
        }
        callee_id = edge.get("callee")
        if edge["kind"] == "resolved" and isinstance(callee_id, str):
            callee = functions.get(callee_id)
            if callee is None:
                type_record = types.get(callee_id)
                callee = type_record
            if callee is None:
                callee = declarations.get(callee_id)
            if callee is not None:
                callee_path = callee["id"].split("::", 1)[0]
                row.update(
                    callee_file=callee_path,
                    callee_name=callee["name"],
                    callee_line=callee["line"],
                )
        result.append(row)
    return result


def _declarations_by_id(facts_by_file: dict) -> dict[str, dict]:
    return {
        record["id"]: record
        for facts in facts_by_file.values()
        for key in ("functions", "types")
        for record in facts.get(key, ())
    }


def _check_deadline(deadline: float | None, timeout_seconds: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError(
            f"quality edge export exceeded timeout of {timeout_seconds} seconds"
        )


def _new_output_path() -> Path:
    descriptor, name = tempfile.mkstemp(prefix="quality-edges-", suffix=".jsonl")
    os.close(descriptor)
    return Path(name)
