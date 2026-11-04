import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier

import pytest
from ledger_backends import Backend, backend_registry
from varde_data.repos.ledger import LedgerRepository


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def backend(request: pytest.FixtureRequest) -> Backend:
    return backend_registry()[request.param]


@pytest.fixture
def store(backend: Backend, tmp_path: Path) -> LedgerRepository:
    return backend.factory(tmp_path)


def test_latest_row_wins_and_seen_is_harness_scoped(store: LedgerRepository) -> None:
    store.mark("codex", "s1", "first", "old")
    store.mark("claude", "s2", "only", "other")
    store.mark("codex", "s1", "latest", "new", {"n": 1}, ["f"])
    assert [(r.harness, r.session, r.summary) for r in store.analyzed()] == [
        ("codex", "s1", "new"),
        ("claude", "s2", "other"),
    ]
    assert store.seen("codex") == {"s1"}


def test_files_ignores_malformed_and_torn_rows(
    backend: Backend, tmp_path: Path
) -> None:
    if backend.name != "files":
        return
    path = tmp_path / "analyzed.jsonl"
    path.write_bytes(
        b'{"session":"good","harness":"h","analyzed_at":"t"}\nnope\n{"session":"torn"'
    )
    store = backend.factory(tmp_path)
    assert [row.session for row in store.analyzed()] == ["good"]
    prefix = path.read_bytes()
    store.mark("h", "next", "t", "summary")
    data = path.read_bytes()
    assert data.startswith(prefix + b"\n")
    assert json.loads(data.splitlines()[-1])["session"] == "next"


def test_files_append_preserves_existing_complete_bytes(tmp_path: Path) -> None:
    path = tmp_path / "analyzed.jsonl"
    store = backend_registry()["files"].factory(tmp_path)
    store.mark("h", "one", "t", "s")
    before = path.read_bytes()
    store.mark("h", "two", "t", "s")
    assert path.read_bytes().startswith(before)
    assert path.stat().st_mode & 0o777 == 0o600


def test_digest_round_trip_and_bad_shapes(
    store: LedgerRepository, backend: Backend, tmp_path: Path
) -> None:
    day = date(2026, 10, 24)
    candidates = [{"title": "candidate"}]
    store.write_digest(day, "digest", candidates)
    digest = store.read_digest(day)
    assert digest is not None
    assert digest.text == "digest"
    assert digest.candidates == candidates
    if backend.name == "files":
        path = tmp_path / "digests" / "2026-10-24.json"
        assert path.read_text().endswith("\n")
        path.write_text("[]")
        assert store.read_digest(day) is None
        path.write_text('{"text":3}')
        assert store.read_digest(day) is None
        path.write_text('{"text":"x","candidates":3}')
        digest = store.read_digest(day)
        assert digest is not None
        assert digest.candidates == 3
        path.write_text('{"text":"x"}')
        digest = store.read_digest(day)
        assert digest is not None
        assert digest.candidates == []


def test_concurrent_marks(backend: Backend, tmp_path: Path) -> None:
    barrier = Barrier(8)
    store = backend.factory(tmp_path)

    def mark(index: int) -> None:
        barrier.wait()
        store.mark("h", str(index), "t", "summary")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(mark, range(8)))
    assert len(store.analyzed()) == 8
