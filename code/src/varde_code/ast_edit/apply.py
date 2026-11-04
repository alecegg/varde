"""Validate and apply a saved AST edit proposal."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def apply(proposal: dict[str, Any], repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")
    if proposal.get("repository_root") != str(root):
        raise ValueError(
            f"proposal repository root does not match canonical repository root {root}"
        )
    if proposal.get("version") != 1:
        raise ValueError("unsupported AST edit proposal version (expected 1)")
    files = proposal.get("files")
    if not proposal.get("complete") or not isinstance(files, list) or not files:
        raise ValueError("proposal is incomplete or contains no file changes")
    if any(item.get("blocking") for item in proposal.get("diagnostics", [])):
        raise ValueError("proposal contains blocking diagnostics")
    scopes = proposal.get("scope", [])
    rules = proposal.get("rules", [])
    rule_ids = {rule.get("id") for rule in rules}
    paths: set[str] = set()
    for change in files:
        relative = Path(change["path"])
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {".", ".."} for part in relative.parts)
        ):
            raise ValueError(
                "proposal path must be a clean relative repository path: "
                f"{change['path']!r}"
            )
        if change["path"] in paths:
            raise ValueError(
                f"proposal contains duplicate file path {change['path']!r}"
            )
        paths.add(change["path"])
        if not any(
            scope == "." or relative.is_relative_to(Path(scope)) for scope in scopes
        ):
            raise ValueError(
                f"proposal file path {change['path']!r} is not in its recorded scope"
            )
        _verify_change(change, rule_ids)
    body = {key: value for key, value in proposal.items() if key != "id"}
    expected_id = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if proposal.get("id") != expected_id:
        raise ValueError("proposal body digest does not match its id")

    targets = []
    for change in files:
        relative = Path(change["path"])
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"proposal target is not a regular file: {path}")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError(f"proposal target resolves outside the repository: {path}")
        current = path.read_bytes()
        if (
            current != change["original_content"].encode()
            or _sha(current) != change["original_sha256"]
        ):
            raise ValueError(f"original snapshot identity changed for {change['path']}")
        targets.append((change, path.resolve()))

    results = []
    for change, target in targets:
        if target.read_bytes() != change["original_content"].encode():
            results.append(
                {
                    "path": change["path"],
                    "status": "source_changed",
                    "detail": "original snapshot changed after preflight",
                }
            )
            continue
        try:
            _atomic_write(target, change["replacement_content"].encode())
            results.append(
                {"path": change["path"], "status": "applied", "detail": None}
            )
        except OSError as error:
            results.append(
                {"path": change["path"], "status": "write_failed", "detail": str(error)}
            )
    return {"proposal_id": proposal["id"], "files": results}


def _verify_change(change: dict[str, Any], rule_ids: set[str]) -> None:
    original = change["original_content"]
    replacement = change["replacement_content"]
    if _sha(original.encode()) != change["original_sha256"]:
        raise ValueError(f"original payload digest does not match for {change['path']}")
    if _sha(replacement.encode()) != change["replacement_sha256"]:
        raise ValueError(
            f"replacement payload digest does not match for {change['path']}"
        )
    spans = change.get("match_spans", [])
    if not spans or len(spans) != change.get("replacement_count"):
        raise ValueError(f"invalid match span count for {change['path']}")
    source, cursor = original.encode(), 0
    output = bytearray()
    for span in spans:
        start, end = span["start_byte"], span["end_byte"]
        if start < cursor or start >= end:
            raise ValueError(f"invalid or overlapping match span for {change['path']}")
        try:
            actual = source[start:end].decode()
        except UnicodeDecodeError as error:
            raise ValueError(
                f"match span is not on UTF-8 boundaries in {change['path']}"
            ) from error
        if actual != span["original"]:
            raise ValueError(
                f"match span original text does not match {change['path']}"
            )
        ids = span.get("rule_ids", [])
        if not ids or any(item not in rule_ids for item in ids):
            raise ValueError(
                f"match span has invalid rule provenance in {change['path']}"
            )
        output.extend(source[cursor:start])
        output.extend(span["replacement"].encode())
        cursor = end
    output.extend(source[cursor:])
    if output.decode() != replacement:
        raise ValueError(
            f"match spans do not produce the saved replacement for {change['path']}"
        )


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, contents: bytes) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
