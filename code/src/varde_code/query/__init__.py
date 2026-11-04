"""Query dispatcher and public mode-registration seam."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never, cast

from varde_code import OutputCapture

from .freshness import source_root_mismatch
from .modes import ModeHandler, get_mode, index_service, register_mode, registered_modes
from .output import render
from .params import QueryError, object_input
from .staleness import STALE_MESSAGE, content_stale, provenance_meta

_FRESHNESS_MODES = {
    "symbols_in_file",
    "get_symbol",
    "filter_symbols",
    "hotspots",
    "tests_for_file",
    "find_imports",
    "dependencies",
    "dependents",
    "blast_radius",
    "symbol_blast_radius",
    "type_hierarchy",
    "explore",
    "map_symbol",
    "map_path",
    "map_file",
    "clusters",
    "context_pack",
    "nav_map",
}
_FRESHNESS_CACHE: dict[tuple[int, str, str], bool] = {}


def _raise_stale_index(message: str | None = None) -> Never:
    raise QueryError(
        "index_stale",
        message
        or "dbPath index was built for another source root or predates "
        "source-root validation",
    )


def dispatch(
    mode: str,
    value: object,
    capture: OutputCapture | None = None,
    *,
    fresh_cache: dict[tuple[str, str], bool] | None = None,
) -> dict[str, Any]:
    try:
        input = object_input(value)
        if mode == "batch":
            return _batch(input, capture)
        service = index_service()
        stale = False
        content_message = None
        provenance: dict[str, Any] | None = None
        if mode in _FRESHNESS_MODES and isinstance(input.get("repoRoot"), str):
            root = input["repoRoot"]
            path = input.get("dbPath")
            if not isinstance(path, str) and service is not None:
                path = str(service.repo_db_path(Path(root)))
                input["dbPath"] = path
            if isinstance(path, str) and service is not None:
                key = (id(service), root, mode)
                if key not in _FRESHNESS_CACHE:
                    _FRESHNESS_CACHE[key] = service.check_fresh(Path(root), mode)
                stale = not _FRESHNESS_CACHE[key]
            elif isinstance(path, str) and Path(path).is_file():
                stale = source_root_mismatch(path, root)
                if not stale and content_stale(path, root, fresh_cache):
                    stale, content_message = True, STALE_MESSAGE
                if not stale:
                    provenance = provenance_meta(path, root)
        if stale:
            _raise_stale_index(content_message)
        input = {**input, "mode": mode}
        if mode == "find_pattern":
            handler = cast(
                "Callable[[dict[str, Any], OutputCapture | None], Any]",
                get_mode(mode),
            )
            result = handler(input, capture)
        else:
            result = get_mode(mode)(input)
        return _with_provenance(render(result, input, capture=capture), provenance)
    except QueryError as exc:
        return render(None, error=(exc.code, exc.message))
    except sqlite3.Error as exc:
        return render(None, error=("db_error", str(exc)))


def _with_provenance(
    rendered: dict[str, Any], provenance: dict[str, Any] | None
) -> dict[str, Any]:
    if provenance and isinstance(rendered.get("meta"), dict):
        rendered["meta"].update(provenance)
    return rendered


def run_mode(mode: str, input: str) -> str:
    try:
        value = json.loads(input)
    except (ValueError, TypeError) as exc:
        result = render(
            None, error=("invalid_input", f"input is not valid JSON: {exc}")
        )
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(dispatch(mode, value), ensure_ascii=False, separators=(",", ":"))


def _batch(input: dict[str, Any], capture: OutputCapture | None) -> dict[str, Any]:
    calls = input.get("calls")
    if not isinstance(calls, list):
        raise QueryError("invalid_input", 'missing array field "calls"')
    fresh_cache: dict[tuple[str, str], bool] = {}
    results = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("mode"), str):
            results.append(
                _batch_error(
                    None, "invalid_input", 'batch call missing string field "mode"'
                )
            )
            continue
        mode = call["mode"]
        if mode == "batch":
            results.append(
                _batch_error(mode, "invalid_input", 'batch calls cannot nest "batch"')
            )
            continue
        merged = dict(call)
        if "repoRoot" not in merged and "repoRoot" in input:
            merged["repoRoot"] = input["repoRoot"]
        if "dbPath" not in merged and "repoRoot" not in call and "dbPath" in input:
            merged["dbPath"] = input["dbPath"]
        result = dispatch(mode, merged, capture, fresh_cache=fresh_cache)
        result["mode"] = mode
        results.append(result)
    return {
        "schema_version": 1,
        "envelope_version": 1,
        "ok": True,
        "outcome": "success",
        "data": results,
        "meta": {"compact": True, "truncated": False},
    }


def _batch_error(mode: str | None, code: str, message: str) -> dict[str, Any]:
    result = render(None, error=(code, message))
    result["mode"] = mode
    return result


def _batch_mode(input: dict[str, Any]) -> dict[str, Any]:
    return _batch(input, None)


register_mode("batch", _batch_mode)

# Import handlers so package-level dispatch and the CLI expose the same modes.
from . import find_pattern as find_pattern  # noqa: E402, RUF100 - handlers register after shared dispatch setup
from . import graph as graph  # noqa: E402, RUF100 - handlers register after shared dispatch setup
from . import mapping as mapping  # noqa: E402, RUF100 - handlers register after shared dispatch setup
from . import nav_map as nav_map  # noqa: E402, RUF100 - handlers register after shared dispatch setup
from . import simple as simple  # noqa: E402, RUF100 - handlers register after shared dispatch setup
from . import slice_state as slice_state  # noqa: E402, RUF100 - handlers register after shared dispatch setup

__all__ = ["ModeHandler", "dispatch", "register_mode", "registered_modes", "run_mode"]
