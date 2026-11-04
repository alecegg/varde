from __future__ import annotations

from pathlib import Path

from varde_data.backends.files.friction import FilesFriction
from varde_data.repos.friction import FrictionAddRequest


def test_refresh_uses_shared_store_lock(tmp_path: Path, monkeypatch) -> None:
    from contextlib import contextmanager

    from varde_data.backends.sqlite import friction as friction_backend

    repository = FilesFriction(tmp_path)
    repository.add(
        FrictionAddRequest(
            title="needle item",
            source="test",
            evidence="evidence",
            cwd=str(tmp_path),
            global_=True,
        )
    )
    lock_paths = []
    real_lock = friction_backend.blocking_file_lock

    @contextmanager
    def record_lock(path, *, mode=0o666):
        lock_paths.append(path)
        with real_lock(path, mode=mode):
            yield

    monkeypatch.setattr(friction_backend, "blocking_file_lock", record_lock)

    repository.list_items(offset=0, limit=5)

    assert lock_paths == [tmp_path / "friction.jsonl", tmp_path / "friction.jsonl"]
