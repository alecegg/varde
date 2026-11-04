from __future__ import annotations

import os
import time

import blake3
from varde_toz.index_files import (
    collect_paths,
    file_meta,
    index_file,
    is_stale,
    refresh_stale,
)
from varde_toz.project import store_db_path
from varde_toz.store import Store


def setup_store(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(config))
    return project, config, Store.open(store_db_path(project, config))


def test_staleness_uses_mtime_then_content_hash(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("hello")
    mtime, digest = file_meta(path, b"hello")
    assert not is_stale(path, mtime, digest)
    assert not is_stale(path, mtime - 100, digest)  # touched, same contents
    path.write_text("changed")
    os.utime(path, ns=(mtime + 100, mtime + 100))
    assert is_stale(path, mtime, digest)
    assert not is_stale(
        path, mtime // 1_000_000_000, blake3.blake3(b"changed").digest()
    )
    assert is_stale(path, mtime // 1_000_000_000, digest)
    path.unlink()
    assert is_stale(path, mtime, digest)


def test_refresh_replaces_changed_index_capture_and_keeps_label(tmp_path, monkeypatch):
    project, _config, store = setup_store(tmp_path, monkeypatch)
    path = project / "notes.txt"
    path.write_text("before content")
    index_file(path, "chosen label", project)
    original = store.list(10, False)
    assert len(original) == 1
    source = original[0]["source"]
    path.write_text("after content")
    os.utime(path, ns=(time.time_ns(), time.time_ns()))
    assert refresh_stale(store, project) == [source]
    live = store.list(10, False)
    assert len(live) == 1
    assert live[0]["label"] == "chosen label"
    all_rows = store.list(10, True)
    assert len(all_rows) == 2
    assert sum(row["superseded_by"] is None for row in all_rows) == 1


def test_refresh_refuses_redacted_explicit_label_and_path(tmp_path, monkeypatch):
    project, config, store = setup_store(tmp_path, monkeypatch)
    path = project / "vault-4217.txt"
    path.write_text("initial")
    config.mkdir(exist_ok=True)
    (config / "config.toml").write_text(
        '[redact]\npatterns = ["vault-[0-9]+", "private-[0-9]+"]\n'
    )
    index_file(path, "private-123", project)
    path.write_text("modified")
    assert refresh_stale(store, project) == []
    assert len(store.list(10, True)) == 1


def test_redacted_path_requires_explicit_reindex(tmp_path, monkeypatch):
    project, config, store = setup_store(tmp_path, monkeypatch)
    path = project / "vault-123.txt"
    path.write_text("original body")
    config.mkdir(exist_ok=True)
    (config / "config.toml").write_text('[redact]\npatterns = ["vault-[0-9]+"]\n')
    index_file(path, None, project)
    row = store.list(1, False)[0]
    assert "vault-123" not in row["source"]
    path.write_text("changed body")
    assert refresh_stale(store, project) == []
    index_file(path, None, project)
    assert len(store.list(1, False)) == 1


def test_long_path_refresh_supersedes_default_label(tmp_path, monkeypatch):
    project, _config, store = setup_store(tmp_path, monkeypatch)
    nested = project / ("a" * 100)
    nested.mkdir()
    path = nested / "indexed.txt"
    path.write_text("before")
    first_mtime = 1_700_000_000_000_000_000
    os.utime(path, ns=(first_mtime, first_mtime))
    index_file(path, None, project)
    source = path.resolve().as_posix()
    path.write_text("after")
    os.utime(path, ns=(first_mtime + 1_000_000_000, first_mtime + 1_000_000_000))
    assert refresh_stale(store, project) == [source]
    assert len(store.list(10, False)) == 1
    all_rows = store.list(10, True)
    assert len(all_rows) == 2
    assert sum(row["superseded_by"] is None for row in all_rows) == 1


def test_path_collection_is_sorted_skips_hidden_and_supports_globs(tmp_path):
    (tmp_path / "z.md").write_text("z")
    (tmp_path / "a.rs").write_text("a")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "private.md").write_text("hidden")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.md").write_text("b")
    assert [p.name for p in collect_paths([tmp_path], False, "*.{md,rs}")] == [
        "a.rs",
        "z.md",
    ]
    assert [p.name for p in collect_paths([tmp_path], True, "*.md")] == ["b.md", "z.md"]


def test_empty_glob_and_missing_path_errors(tmp_path):
    try:
        collect_paths([tmp_path], False, "*.nope")
    except ValueError as exc:
        assert str(exc) == "nothing to index"
    else:
        raise AssertionError("expected empty glob to fail")
    try:
        collect_paths([tmp_path / "missing"], False, None)
    except FileNotFoundError as exc:
        assert "no such file or directory" in str(exc)
    else:
        raise AssertionError("expected missing path to fail")


def test_index_binary_file_reports_skipped_and_fails(tmp_path, monkeypatch, capsys):
    from varde_toz.commands.index import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path / "config"))
    path = tmp_path / "binary.dat"
    path.write_bytes(b"\x00\xffbinary")

    status = main([str(path)])

    assert status == 1
    assert capsys.readouterr().out == f"varde-toz: {path}: not indexed (binary)\n"
