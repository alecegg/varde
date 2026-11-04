"""Implement app capabilities over the code and toz modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from varde_core.io import Io

if TYPE_CHECKING:
    from varde_code import CaptureInput


def error_envelope_code(text: str) -> str | None:
    try:
        value = json.loads(text.strip())
    except ValueError, TypeError:
        return None
    if not isinstance(value, dict) or value.get("ok") is not False:
        return None
    error = value.get("data", {}).get("error", {})
    return (
        error.get("code")
        if isinstance(error, dict) and isinstance(error.get("code"), str)
        else "error"
    )


def dependents_from_envelope(envelope: str) -> list[Path] | None:
    try:
        result = json.loads(envelope)
    except ValueError, TypeError:
        return None
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    if result.get("meta", {}).get("truncated") is True:
        return None
    data = result.get("data")
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        return None
    return [Path(item) for item in data]


def defers_index(label: str) -> bool:
    return label == "find_pattern"


class _CodeImpact:
    def dependents(self, repo_root: Path, file: Path) -> list[Path] | None:
        from varde_code import query
        from varde_code.index.paths import repo_db_path

        payload = json.dumps(
            {
                "repoRoot": str(repo_root),
                "filePath": str(file),
                "dbPath": str(repo_db_path(repo_root)),
                "fullResults": True,
            },
            separators=(",", ":"),
        )

        return dependents_from_envelope(query.run_mode("blast_radius", payload))


class _TozCapture:
    def capture(self, input: CaptureInput, source: str, label: str) -> str | None:
        from varde_toz.capture import CaptureInput as TozInput
        from varde_toz.capture import capture

        stdout = (
            input.text.encode()
            if input.text is not None
            else ("".join(f"{item}\n" for item in input.items or ()).encode())
        )
        result = capture(
            TozInput(
                stdout=stdout,
                label=label,
                source=source,
                kind="capture",
                force=True,
                defer_index=defers_index(label),
            )
        )
        return (
            result.output if result.status == 0 and "handle" in result.output else None
        )


_IMPACT = _CodeImpact()
_CAPTURE = _TozCapture()


def io() -> Io:
    return Io(impact=_IMPACT, capture=_CAPTURE)
