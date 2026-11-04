from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar

from varde_code.index.build import build, make_freshener
from varde_code.index.slice import Scope, Slice
from varde_code.model import ExtractOutput


class FixtureProvider:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        from varde_code.extract.entity import extract_file

        self.paths.append(path)
        return extract_file(str(path), source, language)


def test_full_build_indexes_authored_source_and_persists_derived_data(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (root / "notes.txt").write_text("not source", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = FixtureProvider()

    summary = build(root, provider)

    assert summary.entities == 1
    assert summary.diagnostics == 1
    assert provider.paths == [root / "main.py"]
    with sqlite3.connect(summary.db_path) as connection:
        assert connection.execute(
            "SELECT path FROM files ORDER BY path"
        ).fetchall() == [(str(root / "main.py"),), (str(root / "notes.txt"),)]
        assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT complexity FROM files WHERE path=?", (str(root / "main.py"),)
            ).fetchone()[0]
            > 0
        )
        assert (
            connection.execute(
                "SELECT community_id FROM files WHERE path=?", (str(root / "main.py"),)
            ).fetchone()[0]
            == 1
        )
        assert connection.execute(
            "SELECT file_id,path,message FROM diagnostics"
        ).fetchall() == [
            (2, str(root / "notes.txt"), "unsupported file type — skipped")
        ]
        assert connection.execute(
            "SELECT slice FROM slice_state ORDER BY slice"
        ).fetchall() == [("edges",), ("global",), ("imports",)]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM function_metrics WHERE name='main'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM graph_cache").fetchone() == (1,)


def test_make_freshener_matches_index_service_callback_signature(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    callback = make_freshener(FixtureProvider())

    callback(root, (Slice.GLOBAL,), Scope.repo())

    assert list((tmp_path / "config" / "code" / "repos-py").rglob("index.db"))


def test_incremental_refresh_prunes_deleted_file_and_tracks_stale_source(
    tmp_path, monkeypatch
):
    from varde_code.index.incremental import refresh
    from varde_code.index.slice import IndexService

    root = tmp_path / "repo"
    root.mkdir()
    first = root / "first.py"
    second = root / "second.py"
    third = root / "third.py"
    first.write_text("def first(): pass\n", encoding="utf-8")
    second.write_text("def second(): pass\n", encoding="utf-8")
    third.write_text("def third(): pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    build(root, FixtureProvider())
    service = IndexService()
    assert service.check_fresh(root)

    first.write_text("def changed(): pass\n", encoding="utf-8")
    third.unlink()
    assert not service.check_fresh(root)
    summary = refresh(root, FixtureProvider())

    assert summary.changed_files == (str(first),)
    assert service.check_fresh(root)
    with sqlite3.connect(summary.db_path) as connection:
        assert connection.execute(
            "SELECT path FROM files ORDER BY path"
        ).fetchall() == [(str(first),), (str(second),)]
        assert connection.execute(
            "SELECT name FROM entities ORDER BY name"
        ).fetchall() == [("changed",), ("second",)]


class _SpyExecutor:
    """Run the same initializer and map in-process while recording use."""

    instances: ClassVar[list[_SpyExecutor]] = []

    def __init__(self, max_workers, initializer, initargs):
        initializer(*initargs)
        self.max_workers = max_workers
        self.mapped = 0
        self.shutdowns: list[dict] = []
        type(self).instances.append(self)

    def map(self, function, items, chunksize=1):
        results = [function(item) for item in items]
        self.mapped = len(results)
        return iter(results)

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns.append({"wait": wait, "cancel_futures": cancel_futures})


def _mixed_files(root: Path, count: int):
    from varde_code.index.files import list_source_listing

    root.mkdir()
    for number in range(count):
        (root / f"mod{number}.py").write_text(
            f"def f{number}(a, b):\n    return a + b + {number}\n"
        )
    (root / "bad.py").write_bytes(b"\xff\xfe = 1\n")
    (root / "min.js").write_text("var a=1;" * 5000 + "\n")
    (root / "notes.txt").write_text("text")
    return list_source_listing(root).files


def test_extract_one_skips_bad_utf8_and_minified_sources(tmp_path):
    import varde_code.index.build as build_module
    from varde_code.extract.provider import CodeExtractionProvider

    files = _mixed_files(tmp_path / "repo", 1)
    outputs = {
        Path(f.path).name: build_module._extract_one(f, CodeExtractionProvider())
        for f in files
    }

    assert [d.message for d in outputs["bad.py"].diagnostics] == [
        "binary or non-UTF-8 — skipped"
    ]
    assert [d.message for d in outputs["min.js"].diagnostics] == [
        "minified/generated source — skipped"
    ]
    assert outputs["mod0.py"].diagnostics == []


def test_parallel_extraction_equals_serial_and_uses_pool(tmp_path, monkeypatch):
    import varde_code.index.build as build_module
    from varde_code.extract.provider import CodeExtractionProvider

    files = _mixed_files(tmp_path / "repo", build_module._PARALLEL_MIN_FILES + 4)
    provider = CodeExtractionProvider()
    monkeypatch.setattr(build_module, "_MAX_WORKERS", 1)
    serial = build_module._extract_outputs(files, provider)
    _SpyExecutor.instances.clear()
    monkeypatch.setattr(build_module, "_MAX_WORKERS", 4)
    monkeypatch.setattr("os.process_cpu_count", lambda: 4, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _SpyExecutor)

    parallel = build_module._extract_outputs(files, provider)

    assert parallel == serial
    assert [i.mapped for i in _SpyExecutor.instances] == [len(files)]
    assert _SpyExecutor.instances[0].shutdowns == [
        {"wait": True, "cancel_futures": False}
    ]


def test_real_process_pool_equals_serial(tmp_path, monkeypatch):
    from concurrent.futures import ProcessPoolExecutor

    import pytest
    import varde_code.index.build as build_module
    from varde_code.extract.provider import CodeExtractionProvider

    files = _mixed_files(tmp_path / "repo", build_module._PARALLEL_MIN_FILES + 4)
    provider = CodeExtractionProvider()
    monkeypatch.setattr(build_module, "_MAX_WORKERS", 1)
    serial = build_module._extract_outputs(files, provider)
    ran: list[int] = []

    class Recording(ProcessPoolExecutor):
        def map(self, *args, **kwargs):
            results = list(super().map(*args, **kwargs))
            ran.append(len(results))
            return iter(results)

    monkeypatch.setattr(build_module, "_MAX_WORKERS", 2)
    monkeypatch.setattr("os.process_cpu_count", lambda: 2, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: 2)
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", Recording)

    parallel = build_module._extract_outputs(files, provider)

    if not ran:
        pytest.skip("process pool unavailable in this sandbox")
    assert ran == [len(files)]
    assert parallel == serial


def test_pool_construction_error_falls_back_to_serial(tmp_path, monkeypatch, capsys):
    import varde_code.index.build as build_module
    from varde_code.extract.provider import CodeExtractionProvider

    files = _mixed_files(tmp_path / "repo", build_module._PARALLEL_MIN_FILES + 4)
    provider = CodeExtractionProvider()
    monkeypatch.setattr(build_module, "_MAX_WORKERS", 1)
    serial = build_module._extract_outputs(files, provider)

    def refuse(**_kwargs):
        raise PermissionError("sem_open denied")

    monkeypatch.setattr(build_module, "_MAX_WORKERS", 4)
    monkeypatch.setattr("os.process_cpu_count", lambda: 4, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", refuse)

    assert build_module._extract_outputs(files, provider) == serial
    assert "process pool unavailable" in capsys.readouterr().err


def test_broken_pool_falls_back_to_serial(tmp_path, monkeypatch, capsys):
    from concurrent.futures.process import BrokenProcessPool

    import varde_code.index.build as build_module
    from varde_code.extract.provider import CodeExtractionProvider

    files = _mixed_files(tmp_path / "repo", build_module._PARALLEL_MIN_FILES + 4)
    provider = CodeExtractionProvider()
    monkeypatch.setattr(build_module, "_MAX_WORKERS", 1)
    serial = build_module._extract_outputs(files, provider)

    class Broken(_SpyExecutor):
        def map(self, function, items, chunksize=1):
            raise BrokenProcessPool("worker died")

    Broken.instances = []
    monkeypatch.setattr(build_module, "_MAX_WORKERS", 4)
    monkeypatch.setattr("os.process_cpu_count", lambda: 4, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", Broken)

    assert build_module._extract_outputs(files, provider) == serial
    assert "process pool failed" in capsys.readouterr().err
    assert Broken.instances[0].shutdowns[0]["cancel_futures"] is True


def test_interrupt_cancels_pending_chunks_and_reraises(tmp_path, monkeypatch):
    import pytest
    import varde_code.index.build as build_module
    from varde_code.extract.provider import CodeExtractionProvider

    files = _mixed_files(tmp_path / "repo", build_module._PARALLEL_MIN_FILES + 4)

    class Interrupted(_SpyExecutor):
        instances: ClassVar[list[_SpyExecutor]] = []

        def map(self, function, items, chunksize=1):
            raise KeyboardInterrupt

    monkeypatch.setattr(build_module, "_MAX_WORKERS", 4)
    monkeypatch.setattr("os.process_cpu_count", lambda: 4, raising=False)
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", Interrupted)

    with pytest.raises(KeyboardInterrupt):
        build_module._extract_outputs(files, CodeExtractionProvider())

    assert Interrupted.instances[0].shutdowns == [
        {"wait": False, "cancel_futures": True}
    ]
