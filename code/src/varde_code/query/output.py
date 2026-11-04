"""Query result envelopes, compact paths, and bounded result paging."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from varde_core.envelope import success, tool_error

from varde_code import OutputCapture
from varde_code.query.context_budget import fit_sections

DEFAULT_QUERY_LIMIT = 100
# Rust switches captured compact pages to its Toz page size (toz.rs:14).
COMPACT_QUERY_LIMIT = 20
PATH_KEYS = {
    "file",
    "filePath",
    "path",
    "source",
    "test_file",
    "testFile",
    "to",
    "coversFile",
}
PATH_LIST_KEYS = {"files", "members", "readingOrder"}


def _relative_path(value: str, root: str) -> str:
    if not Path(root).is_absolute() or not Path(value).is_absolute():
        return value
    try:
        return Path(value).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return value


def _walk_paths(value: Any, root: str, absolute: bool) -> Any:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in PATH_KEYS and isinstance(item, str) and not absolute:
                value[key] = _relative_path(item, root)
            elif key in PATH_LIST_KEYS and isinstance(item, list) and not absolute:
                value[key] = [
                    _relative_path(path, root)
                    if isinstance(path, str)
                    else _walk_paths(path, root, absolute)
                    for path in item
                ]
            else:
                value[key] = _walk_paths(item, root, absolute)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _walk_paths(item, root, absolute)
    return value


def compact(data: Any, input: dict[str, Any]) -> bool:
    root = input.get("repoRoot")
    if not isinstance(root, str):
        return False
    absolute = input.get("absolutePaths") is True
    _walk_paths(data, root, absolute)
    if input.get("includeSpanDetail") is not True:
        _trim_spans(data)
    return not absolute or input.get("includeSpanDetail") is not True


def _trim_spans(value: Any) -> None:
    if isinstance(value, dict):
        span = value.get("span")
        if isinstance(span, dict):
            for key in ("start_byte", "end_byte", "start_col", "end_col"):
                span.pop(key, None)
        for child in value.values():
            _trim_spans(child)
    elif isinstance(value, list):
        for child in value:
            _trim_spans(child)


def paginate(
    data: Any, input: dict[str, Any], mode: str, capture: OutputCapture | None = None
) -> tuple[Any, dict[str, Any] | None]:
    full = input.get("fullResults", False)
    if not isinstance(full, bool):
        raise ValueError("fullResults must be a boolean")
    default_limit = DEFAULT_QUERY_LIMIT
    limit = input.get("resultsLimit", default_limit)
    offset = input.get("resultsOffset", 0)
    for name, value in (("resultsLimit", limit), ("resultsOffset", offset)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if limit == 0:
        raise ValueError("resultsLimit must be greater than zero")
    key = "blast_radius" if mode == "symbol_blast_radius" else "results"
    target = (
        data.get(key)
        if isinstance(data, dict) and mode == "symbol_blast_radius"
        else data
    )
    if mode == "symbols_in_files" and isinstance(data, dict):
        flattened = [
            item
            for path in sorted(data)
            for item in (data[path] if isinstance(data[path], list) else [])
        ]
        total = len(flattened)
        reference = _capture_page(capture, mode, flattened, offset, limit, full)
        if reference and "resultsLimit" not in input:
            limit = _page_limit()
        start = min(offset, total)
        end = total if full else min(start + limit, total)
        if start == 0 and end == total:
            return data, None
        cursor = 0
        for path in sorted(data):
            values = data[path]
            if isinstance(values, list):
                length = len(values)
                lo, hi = max(0, start - cursor), max(0, min(length, end - cursor))
                values[:] = values[lo:hi]
                cursor += length
        page = _with_toz(
            _page_meta(total, start, end, limit, full), reference, end, limit
        )
        toz = page.pop("__toz", None)
        return data, _SymbolsPageMeta(page, toz)
    if (
        mode == "context_pack"
        and isinstance(data, dict)
        and isinstance(data.get("files"), list)
    ):
        return _paginate_context_pack(data, input, capture, limit, offset, full)
    if not isinstance(target, list):
        return data, None
    total = len(target)
    reference = _capture_page(capture, mode, target, offset, limit, full)
    if reference and "resultsLimit" not in input:
        limit = _page_limit()
    start = min(offset, total)
    end = total if full else min(start + limit, total)
    if start == 0 and end == total:
        return data, None
    if isinstance(data, dict) and mode == "symbol_blast_radius":
        data[key] = target[start:end]
    else:
        data = target[start:end]
    details = _with_toz(
        _page_meta(total, start, end, limit, full), reference, end, limit
    )
    toz = details.pop("__toz", None)
    page = details
    if toz:
        page["__toz"] = toz
    return data, page


CONTEXT_PACK_DEFAULT_TOKENS = 4000
# Bytes kept for the success envelope around data (ok, outcome, meta, toz).
_ENVELOPE_RESERVE_BYTES = 600


def _context_token_budget(input: dict[str, Any]) -> int:
    value = input.get("maxTokensEstimate", CONTEXT_PACK_DEFAULT_TOKENS)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("maxTokensEstimate must be a positive integer")
    return value


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")).encode())


def _paginate_context_pack(
    data: dict[str, Any],
    input: dict[str, Any],
    capture: OutputCapture | None,
    limit: int,
    offset: int,
    full: bool,
) -> tuple[Any, dict[str, Any] | None]:
    token_budget = _context_token_budget(input)
    files = data["files"]
    total_files = len(files)
    reference = _capture_page(capture, "context_pack", files, offset, limit, full)
    if reference and "resultsLimit" not in input:
        limit = _page_limit()
    start = min(offset, total_files)
    end = total_files if full else min(start + limit, total_files)
    if start == 0 and end == total_files and full:
        return data, None
    rank = {
        item.get("path"): index
        for index, item in enumerate(files)
        if isinstance(item, dict)
    }
    shown = files[start:end]
    candidates = _page_candidates(data, _paths(shown), rank, total_files)
    for name, items in candidates.items():
        data[name] = items if full else items[:limit]
    if not full:
        shown = _fit_context_budget(data, shown, token_budget)
    data["files"] = shown
    shown_paths = _paths(shown)
    totals: dict[str, int] = {}
    for name, key in _SECTION_KEYS.items():
        data[name] = [item for item in data[name] if item.get(key) in shown_paths]
        totals[name] = sum(1 for i in candidates[name] if i.get(key) in shown_paths)
    if isinstance(data.get("readingOrder"), list):
        data["readingOrder"] = [p for p in data["readingOrder"] if p in shown_paths]
    pagination: dict[str, Any] = {}
    end = start + len(shown)
    if start > 0 or end < total_files:
        details = _page_meta(total_files, start, end, limit, full)
        if reference:
            details = _with_toz(details, reference, end, limit)
            details.pop("__toz", None)
        pagination["files"] = details
    for name in _SECTION_KEYS:
        if len(data[name]) < totals[name]:
            pagination[name] = _section_meta(len(data[name]), totals[name], limit)
    if not pagination:
        return data, None
    return data, {**pagination, "__toz": reference}


_SECTION_KEYS = {"symbols": "filePath", "tests": "coversFile"}


def _paths(files: list[Any]) -> set[Any]:
    return {item.get("path") for item in files if isinstance(item, dict)}


def _page_candidates(
    data: dict[str, Any], shown_paths: set[Any], rank: dict[Any, int], missing: int
) -> dict[str, list[Any]]:
    """Symbols and tests of the shown files, best-ranked file first."""
    candidates = {}
    for name, key in _SECTION_KEYS.items():
        kept = [i for i in data.get(name) or [] if i.get(key) in shown_paths]
        kept.sort(key=lambda item: rank.get(item.get(key), missing))
        candidates[name] = kept
    return candidates


def _section_meta(shown: int, total: int, limit: int) -> dict[str, Any]:
    return {
        "shown": shown,
        "total": total,
        "limit": limit,
        "next_offset": None,
        "request": (
            "lowest-ranked items of the shown files were cut (total counts "
            "the shown files only; other files' items come with their file "
            "page via next_offset); raise resultsLimit or maxTokensEstimate, "
            "or set fullResults to true"
        ),
    }


def _fit_context_budget(
    data: dict[str, Any], shown: list[Any], token_budget: int
) -> list[Any]:
    reading = (
        set(data["readingOrder"])
        if isinstance(data.get("readingOrder"), list)
        else set()
    )
    costs = {
        "files": [
            _json_bytes(item)
            + 1
            + (_json_bytes(item["path"]) + 1 if item.get("path") in reading else 0)
            for item in shown
        ],
        "symbols": [_json_bytes(item) + 1 for item in data["symbols"]],
        "tests": [_json_bytes(item) + 1 for item in data["tests"]],
    }
    pagination_reserve = _json_bytes(
        {name: _section_meta(10**6, 10**6, 10**6) for name in costs}
    )
    budget = token_budget * 4 - _ENVELOPE_RESERVE_BYTES - pagination_reserve
    kept = fit_sections(costs, budget)
    data["symbols"] = data["symbols"][: kept["symbols"]]
    data["tests"] = data["tests"][: kept["tests"]]
    # Keep one file so a paging caller always advances.
    return shown[: max(1, kept["files"])]


def _page_limit() -> int:
    from varde_code.toz_bridge import PAGE_LIMIT

    return PAGE_LIMIT


class _SymbolsPageMeta(dict[str, Any]):
    def __init__(self, results: dict[str, Any], toz: dict[str, Any] | None) -> None:
        super().__init__({"results": results, **({"__toz": toz} if toz else {})})
        self.results = results

    def __getitem__(self, key: str) -> Any:
        if key not in self and key in self.results:
            return self.results[key]
        return super().__getitem__(key)


def _capture_page(
    capture: OutputCapture | None,
    mode: str,
    values: list[Any],
    offset: int,
    limit: int,
    full: bool,
) -> dict[str, Any] | None:
    if full or not (offset > 0 or len(values) > limit):
        return None
    from varde_code.toz_bridge import capture_items

    return capture_items(capture, mode, values)


def _with_toz(
    meta: dict[str, Any], reference: dict[str, Any] | None, end: int, limit: int
) -> dict[str, Any]:
    if reference is None:
        return meta
    meta["__toz"] = reference
    meta["toz_read"] = (
        f"varde run query --handle {reference['handle']} --lines "
        f"{end + 1}:{min(end + limit, reference['items'])}"
    )
    meta["toz_search"] = f'varde run query --handle {reference["handle"]} "<term>"'
    return meta


def _page_meta(
    total: int, start: int, end: int, limit: int, full: bool
) -> dict[str, Any]:
    return {
        "shown": end - start,
        "total": total,
        "offset": start,
        "limit": None if full else limit,
        "next_offset": end if end < total else None,
        "request": "set resultsOffset to next_offset, or set fullResults to true"
        if end < total
        else "set fullResults to true for all results",
    }


def render(
    result: Any,
    input: dict[str, Any] | None = None,
    *,
    error: tuple[str, str] | None = None,
    capture: OutputCapture | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"compact": False, "truncated": False}
    if error:
        result = tool_error(error[0], error[1])
        result["meta"] = meta
        if error[0] == "index_missing" and "find_pattern needs no index" in error[1]:
            result.pop("envelope_version", None)
            return dict(sorted(result.items()))
        return result
    payload = result
    if input is not None:
        compact(payload, input)
        try:
            payload, page = paginate(payload, input, input.get("mode", ""), capture)
        except ValueError as exc:
            result = tool_error("invalid_input", str(exc))
            result["meta"] = meta
            return result
        meta["compact"] = True
        if page is not None:
            meta["toz"] = page.pop("__toz", None)
            if meta["toz"] is None:
                meta.pop("toz")
            if (
                not isinstance(page, _SymbolsPageMeta)
                and input.get("mode") != "context_pack"
                and "files" not in page
            ):
                section = (
                    "blast_radius"
                    if input.get("mode") == "symbol_blast_radius"
                    else "results"
                )
                page = {section: page}
            meta["pagination"] = page
            meta["truncated"] = True
    if isinstance(payload, dict) and payload.get("guide", {}).get("toz"):
        meta["toz"] = payload["guide"]["toz"]
    if isinstance(payload, dict) and payload.get("guide", {}).get("truncated"):
        meta["truncated"] = True
    result = success(payload, meta)
    if isinstance(payload, dict) and {"results", "summary", "diagnostics"}.issubset(
        payload
    ):
        result.pop("envelope_version", None)
        return dict(sorted(result.items()))
    return result
