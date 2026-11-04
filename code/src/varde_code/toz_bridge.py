"""Best-effort bridge from code output to the OutputCapture contract."""

from __future__ import annotations

import json
import os
from typing import Any

from varde_code import CaptureInput, OutputCapture

PAGE_LIMIT = 20


def enabled() -> bool:
    return os.environ.get("VARDE_CODE_TOZ") != "0"


def available(capture: OutputCapture | None) -> bool:
    return enabled() and capture is not None


def capture_text(
    capture: OutputCapture | None, source: str, label: str, text: str
) -> str | None:
    if capture is None or not enabled():
        return None
    try:
        result = capture.capture(CaptureInput.from_text(text), source, label)
    except Exception:
        return None
    return result if result and "handle" in result else None


def capture_items(
    capture: OutputCapture | None, mode: str, items: list[Any]
) -> dict[str, Any] | None:
    if capture is None or not enabled():
        return None
    source = f"varde map results {mode}"
    lines = [
        json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in items
    ]
    try:
        stdout = capture.capture(CaptureInput.from_items(lines), source, mode)
    except Exception:
        return None
    if not stdout or "handle" not in stdout:
        return None
    try:
        response = json.loads(stdout)
    except TypeError, json.JSONDecodeError:
        return None
    handle = response.get("handle")
    if not isinstance(handle, str):
        return None
    return {
        "handle": handle,
        "items": len(items),
        "format": "jsonl",
        "toc": _compact_toc(response),
    }


def _compact_toc(response: dict[str, Any]) -> Any:
    entries = response.get("toc")
    if not isinstance(entries, list):
        return response.get("preview")
    output = ""
    for index, entry in enumerate(entries):
        title = entry.get("title", "other")
        line = (
            f"{title}: {entry.get('items', 0)} items "
            f"(L{entry.get('line_start', 0)}-L{entry.get('line_end', 0)})\n"
        )
        if len(output) + len(line) > 3800:
            output += (
                f"... {len(entries) - index} more file sections; query the handle "
                "for all results"
            )
            break
        output += line
    return output


def add_guide(
    guide: dict[str, Any], reference: dict[str, Any], start: int, end: int
) -> None:
    handle = reference.get("handle")
    if not isinstance(handle, str):
        return
    if start < end:
        guide["toz_read"] = (
            f"varde run query --handle {handle} --lines {start + 1}:{end}"
        )
    guide["toz_search"] = f'varde run query --handle {handle} "<term>"'
