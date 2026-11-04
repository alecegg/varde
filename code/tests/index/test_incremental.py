from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_code.index.build import build
from varde_code.index.files import SourceFile
from varde_code.index.incremental import classify_files, refresh
from varde_code.index.slice import check_fresh, dump_state
from varde_code.model import Diagnostic, Entity, EntityKind, ExtractOutput, Span


class Provider:
    def __init__(self):
        self.calls = []

    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        self.calls.append(path)
        return ExtractOutput()


class ImportProvider:
    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        output = ExtractOutput(
            entities=[
                Entity(EntityKind.FUNCTION, path.stem, 0, Span(0, 1, 1, 0, 1, 1)),
            ]
        )
        if "import helper" in source:
            output.entities.append(
                Entity(EntityKind.IMPORT, ".helper", 0, Span(0, 1, 1, 0, 1, 1))
            )
        return output


def test_classify_files_detects_content_change_new_and_deleted(tmp_path):
    current = [
        SourceFile(str(tmp_path / "a.py"), 1, 1, "new"),
        SourceFile(str(tmp_path / "b.py"), 1, 1, "same"),
    ]

    result = classify_files(
        {
            str(tmp_path / "a.py"): "old",
            str(tmp_path / "b.py"): "same",
            str(tmp_path / "gone.py"): "gone",
        },
        current,
    )

    assert [(item.path, item.status) for item in result] == [
        (str(tmp_path / "a.py"), "changed"),
        (str(tmp_path / "b.py"), "unchanged"),
        (str(tmp_path / "gone.py"), "deleted"),
    ]


def test_no_change_refresh_does_not_extract_or_write(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    initial = build(root, provider)
    refresh(root, provider)  # Store hashes for indexes made before incremental refresh.
    provider.calls.clear()
    db_path = Path(initial.db_path)
    before = db_path.read_bytes()

    summary = refresh(root, provider)

    assert provider.calls == []
    assert summary.unchanged == 1
    assert summary.reparsed == 0
    assert db_path.read_bytes() == before
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT content_hash FROM files").fetchone()[0]


def test_changed_file_refresh_extracts_only_changed_path(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "first.py"
    second = root / "second.py"
    first.write_text("pass\n", encoding="utf-8")
    second.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    build(root, provider)
    refresh(root, provider)
    provider.calls.clear()
    first.write_text("pass  # changed\n", encoding="utf-8")

    summary = refresh(root, provider)

    assert provider.calls == [first]
    assert summary.reparsed == 1
    assert summary.changed_files == (str(first),)


def test_refresh_with_unsupported_files_succeeds_and_stays_fresh(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n", encoding="utf-8")
    (root / "README.md").write_text("notes\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()

    initial = build(root, provider)
    initial_refresh = refresh(root, provider)
    assert initial_refresh.reparsed == 0
    source.write_text("pass  # changed\n", encoding="utf-8")
    summary = refresh(root, provider)

    assert summary.changed_files == (str(source),)
    assert check_fresh(initial.db_path, root)
    with sqlite3.connect(initial.db_path) as connection:
        assert connection.execute(
            "SELECT path FROM files ORDER BY path"
        ).fetchall() == [(str(root / "README.md"),), (str(source),)]
        assert connection.execute(
            "SELECT churn FROM files WHERE path=?", (str(source),)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT path,message FROM diagnostics WHERE file_id IS NOT NULL"
        ).fetchall() == [(str(root / "README.md"), "unsupported file type — skipped")]


def test_incremental_edit_add_delete_matches_fresh_build(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("import helper\n", encoding="utf-8")
    (root / "helper.py").write_text("pass\n", encoding="utf-8")
    (root / "README.md").write_text("notes\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = ImportProvider()
    initial = build(root, provider)
    refresh(root, provider)

    (root / "app.py").write_text("pass\n", encoding="utf-8")
    (root / "extra.py").write_text("pass\n", encoding="utf-8")
    (root / "helper.py").unlink()
    refresh(root, provider)
    incremental_state = _normalized_state(Path(initial.db_path))

    full = build(root, provider)

    assert _normalized_state(Path(full.db_path)) == incremental_state
    assert check_fresh(full.db_path, root)


def test_refresh_advances_revision_and_graph_cache(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    initial = build(root, provider)
    refresh(root, provider)
    source.write_text("changed\n", encoding="utf-8")
    refresh(root, provider)

    state = dump_state(db_path=initial.db_path)
    with sqlite3.connect(initial.db_path) as connection:
        max_rev = connection.execute("SELECT MAX(rev) FROM files").fetchone()[0]
        graph_rev = connection.execute(
            "SELECT rev FROM graph_cache WHERE id=1"
        ).fetchone()[0]
    assert state["next_rev"] > max_rev
    assert graph_rev == max_rev


def test_refresh_replaces_walk_diagnostics(tmp_path, monkeypatch):
    from varde_code.index import _refresh_fastpath
    from varde_code.index import files as index_files
    from varde_code.index.files import SourceListing, list_source_listing

    root = tmp_path / "repo"
    root.mkdir()
    source = root / "main.py"
    source.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = Provider()
    initial = build(root, provider)
    diagnostic = Diagnostic(
        None, str(root / "blocked"), "directory traversal failed", "error"
    )
    monkeypatch.setattr(_refresh_fastpath, "unchanged_summary", lambda _root: None)
    monkeypatch.setattr(
        index_files,
        "list_source_listing",
        lambda _root: SourceListing(list_source_listing(root).files, [diagnostic]),
    )

    refresh(root, provider)
    with sqlite3.connect(initial.db_path) as connection:
        assert connection.execute(
            "SELECT path,message FROM diagnostics WHERE file_id IS NULL ORDER BY path"
        ).fetchall() == [(str(root / "blocked"), "directory traversal failed")]

    monkeypatch.setattr(
        index_files, "list_source_listing", lambda _root: list_source_listing(root)
    )
    refresh(root, provider)
    with sqlite3.connect(initial.db_path) as connection:
        assert (
            connection.execute(
                "SELECT path,message FROM diagnostics WHERE file_id IS NULL"
            ).fetchall()
            == []
        )


def test_metadata_classifier_hashes_when_metadata_is_unknown(tmp_path):
    from varde_code.index.files import _content_hash
    from varde_code.index.incremental import _classify_metadata

    source = tmp_path / "unknown.py"
    source.write_text("pass\n", encoding="utf-8")
    digest = _content_hash(source.read_bytes())
    current = SourceFile(str(source), -1, -1)

    result = _classify_metadata({str(source): (-1, -1, digest, 7)}, [current])

    assert [(item.path, item.status) for item in result] == [(str(source), "unchanged")]


def _normalized_state(db_path: Path):
    with sqlite3.connect(db_path) as connection:
        files = [
            row[0] for row in connection.execute("SELECT path FROM files ORDER BY path")
        ]
        entities = connection.execute(
            "SELECT f.path,e.kind,e.name,e.start_byte,e.end_byte FROM entities e "
            "JOIN files f ON f.id=e.file_id ORDER BY f.path,e.kind,e.name,e.start_byte"
        ).fetchall()
        edges = connection.execute(
            "SELECT source.path,target.path,e.kind,e.resolved FROM resolved_edges e "
            "JOIN files source ON source.id=e.from_file_id "
            "LEFT JOIN files target ON target.id=e.to_file_id "
            "ORDER BY source.path,target.path,e.kind,e.resolved"
        ).fetchall()
        diagnostics = connection.execute(
            "SELECT f.path,d.path,d.message,d.severity FROM diagnostics d "
            "LEFT JOIN files f ON f.id=d.file_id "
            "ORDER BY f.path,d.path,d.message,d.severity"
        ).fetchall()
        communities = connection.execute(
            "SELECT f.path FROM community_members m JOIN files f ON f.id=m.file_id "
            "ORDER BY f.path"
        ).fetchall()
    return files, entities, edges, diagnostics, communities
