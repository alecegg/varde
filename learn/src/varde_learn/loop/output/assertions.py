"""Evaluate fixture assertions against an eval sandbox."""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any


def snapshot(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in _files_under(root)}


def verify(
    assertions: list[dict[str, Any]],
    sandbox: Path,
    transcript: str,
    before: dict[Path, bytes],
) -> list[dict[str, Any]]:
    results = []
    for assertion in assertions:
        kind = assertion.get("kind", "unknown")
        passed, evidence = False, "unknown assertion kind"
        if kind == "file_contains":
            path = _safe_path(sandbox, assertion.get("path", ""))
            with contextlib.suppress(OSError, UnicodeError):
                passed = (
                    path is not None
                    and assertion.get("contains", "") in path.read_text()
                )
            evidence = (
                "file contains expected text"
                if passed
                else "file does not contain expected text"
            )
        elif kind == "file_absent":
            path = _safe_path(sandbox, assertion.get("path", ""))
            passed = path is not None and not path.exists()
            evidence = "file is absent" if passed else "file exists or path is invalid"
        elif kind == "command_exit":
            command = assertion.get("command", "")
            try:
                code = subprocess.run(  # noqa: S603 - Runs the configured assertion command via sh -c.
                    ["sh", "-c", command],  # noqa: S607 - Uses the system shell to evaluate the configured assertion.
                    cwd=sandbox,
                    check=False,
                ).returncode
            except OSError:
                code = None
            passed = bool(command) and code == assertion.get("exit_code", 0)
            evidence = (
                "command exit code matched" if passed else "command exit code differed"
            )
        elif kind == "event_order":
            offset = 0
            events = assertion.get("events", [])
            passed = bool(events)
            for event in events:
                if (
                    not isinstance(event, str)
                    or (found := transcript.find(event, offset)) < 0
                ):
                    passed = False
                    break
                offset = found + len(event)
            evidence = (
                "events appeared in the requested order"
                if passed
                else "events were missing or out of order"
            )
        elif kind == "no_write_outside":
            after = set(_files_under(sandbox))
            changed = {
                path
                for path in after
                if (sandbox / path).read_bytes() != before.get(path)
            }
            changed.update(path for path in before if not (sandbox / path).exists())
            allowed = [
                Path(path)
                for path in assertion.get("allowed_paths", [])
                if isinstance(path, str)
            ]
            passed = all(
                any(path == root or root in path.parents for root in allowed)
                for path in changed
            )
            evidence = (
                "sandbox files stayed within allowed paths"
                if passed
                else "sandbox contains a file outside allowed paths"
            )
        results.append({"kind": kind, "passed": passed, "evidence": evidence})
    return results


def _safe_path(root: Path, relative: str) -> Path | None:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        return None
    return root / path


def _files_under(root: Path) -> list[Path]:
    try:
        return [path for path in root.rglob("*") if path.is_file()]
    except OSError:
        return []
