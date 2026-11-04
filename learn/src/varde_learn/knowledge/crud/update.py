"""Update a concept document with optimistic concurrency protection."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Never

from varde_learn.knowledge.concept import Concept
from varde_learn.knowledge.crud import ConceptIoError, concept_path_or
from varde_learn.knowledge.frontmatter import FrontmatterError
from varde_learn.knowledge.occ import version


def _raise(error: Exception) -> Never:
    raise error


class UpdateError(Exception):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        slug: str | None = None,
        path: Path | None = None,
        source: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.slug = slug
        self.path = path
        self.source = source


@dataclass(frozen=True)
class UpdatedConcept:
    slug: str
    old_version: str
    new_version: str


@contextmanager
def _slug_lock(bundle: Path, slug: str) -> Iterator[None]:
    """Hold a process-shared advisory lock for a concept mutation."""
    path = concept_path_or(bundle, slug)
    if not bundle.is_dir():
        yield
        return
    try:
        canonical_bundle = bundle.resolve()
        canonical_path = path.resolve(strict=False)
        lock_slug = canonical_path.relative_to(canonical_bundle).as_posix()
    except OSError, ValueError:
        lock_slug = slug
    digest = hashlib.sha256(
        b"knowledge\0concept-slug-lock\0v1\0" + lock_slug.encode()
    ).hexdigest()
    lock_path = bundle / f".varde-lock-v1-{digest}.lock"
    try:
        with lock_path.open("a+b") as lock_file:
            deadline = time.monotonic() + 2.0
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"timed out acquiring concept lock {lock_path}"
                        ) from None
                    time.sleep(0.005)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise UpdateError(
            "write_failed", str(exc), slug=slug, path=lock_path, source=exc
        ) from exc


def _read_current(path: Path, slug: str) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        error = ConceptIoError("not_found", slug=slug, path=path, source=exc)
        raise UpdateError(
            error.kind, str(error), slug=slug, path=path, source=error
        ) from exc
    except OSError as exc:
        error = ConceptIoError("read_failed", slug=slug, path=path, source=exc)
        raise UpdateError(
            error.kind, str(error), slug=slug, path=path, source=error
        ) from exc
    return data, version(data)


def _replace_if_unchanged(path: Path, slug: str, expected: str, data: bytes) -> None:
    _, actual = _read_current(path, slug)
    if actual != expected:
        error = ConceptIoError("conflict", slug=slug, path=path)
        raise UpdateError(error.kind, str(error), slug=slug, path=path, source=error)
    fd, stage_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck immediately before the atomic replacement.
        _, actual = _read_current(path, slug)
        if actual != expected:
            error = ConceptIoError("conflict", slug=slug, path=path)
            _raise(
                UpdateError(error.kind, str(error), slug=slug, path=path, source=error)
            )
        os.replace(stage, path)
    except UpdateError:
        raise
    except OSError as exc:
        error = ConceptIoError("write_failed", slug=slug, path=path, source=exc)
        raise UpdateError(
            error.kind, str(error), slug=slug, path=path, source=error
        ) from exc
    finally:
        stage.unlink(missing_ok=True)


def update(
    bundle: str | Path, slug: str, expected_version: str, data: bytes
) -> UpdatedConcept:
    """Replace a valid concept only when its current version matches."""
    bundle = Path(bundle)
    try:
        with _slug_lock(bundle, slug):
            path = concept_path_or(bundle, slug)
            _, actual = _read_current(path, slug)
            if actual != expected_version:
                error = ConceptIoError("conflict", slug=slug, path=path)
                _raise(
                    UpdateError(
                        error.kind, str(error), slug=slug, path=path, source=error
                    )
                )
            try:
                Concept.from_bytes(data, slug)
            except FrontmatterError as exc:
                raise UpdateError(
                    "invalid_concept", str(exc), slug=slug, path=path, source=exc
                ) from exc
            _replace_if_unchanged(path, slug, actual, data)
    except UpdateError:
        raise
    except ConceptIoError as exc:
        raise UpdateError(
            exc.kind, str(exc), slug=slug, path=exc.path, source=exc
        ) from exc
    return UpdatedConcept(slug, actual, version(data))


__all__ = ["UpdateError", "UpdatedConcept", "update"]
