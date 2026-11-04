from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest
from varde_data.fixture_domain import NotesRepository
from varde_data.testing import BackendFactory, backend_registry


@pytest.fixture(scope="module", autouse=True)
def _spawn_processes() -> None:
    multiprocessing.set_start_method("spawn", force=True)


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def notes_factory(request: pytest.FixtureRequest) -> BackendFactory:
    return backend_registry()[request.param]


@pytest.fixture
def notes(notes_factory: BackendFactory, tmp_path: Path) -> NotesRepository:
    return notes_factory(tmp_path)


@pytest.fixture(
    params=tuple(name for name in backend_registry() if name == "files"),
    ids=lambda name: name,
)
def shared_notes_factory(request: pytest.FixtureRequest) -> BackendFactory:
    return backend_registry()[request.param]


@pytest.fixture
def shared_notes(
    shared_notes_factory: BackendFactory, tmp_path: Path
) -> NotesRepository:
    return shared_notes_factory(tmp_path)


assert {"memory", "files"}.issubset(backend_registry())
