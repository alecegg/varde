"""Recursive visitor for concept documents in a bundle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from varde_learn.knowledge.bundle import is_artifact_dir
from varde_learn.knowledge.frontmatter import FrontmatterError, parse


@dataclass
class WalkedFile:
    path: Path
    frontmatter: dict[str, object]
    body: str


class WalkError(OSError):
    """A bundle directory or concept file could not be read or parsed."""

    def __init__(self, kind: str, path: Path, source: Exception) -> None:
        super().__init__(f"{kind}: {path}: {source}")
        self.kind = kind
        self.path = path
        self.source = source


def visit_concepts(
    bundle: Path, reserved: Callable[[str], bool], visitor: Callable[[WalkedFile], None]
) -> None:
    """Visit parsed markdown concepts, aborting on the first error."""
    _visit_dir(bundle, reserved, visitor)


def _visit_dir(
    directory: Path,
    reserved: Callable[[str], bool],
    visitor: Callable[[WalkedFile], None],
) -> None:
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise WalkError("read_dir_failed", directory, exc) from exc

    for path in entries:
        name = path.name
        if name.startswith(".") or is_artifact_dir(name) or path.is_symlink():
            continue
        if path.is_dir():
            _visit_dir(path, reserved, visitor)
            continue
        if not path.is_file() or reserved(name) or not name.endswith(".md"):
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise WalkError("read_failed", path, exc) from exc
        try:
            frontmatter, body = parse(data)
        except (FrontmatterError, ValueError) as exc:
            raise WalkError("invalid_concept", path, exc) from exc
        visitor(WalkedFile(path, frontmatter, body))
