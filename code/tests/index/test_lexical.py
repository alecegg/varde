from __future__ import annotations

import sqlite3

from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.index.lexical import lexical_search


class Provider:
    def extract(self, path, source, language):
        from varde_code.extract.entity import extract_file

        return extract_file(str(path), source, language)


def test_build_populates_fts_and_searches_docstring(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        'def run():\n    """quasar documentation token"""\n    return 1\n'
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    summary = build(root, Provider())

    with sqlite3.connect(summary.db_path) as connection:
        results = lexical_search(connection, "quasar", 10)
        assert len(results) == 1
        entity_id = connection.execute(
            "SELECT id FROM entities WHERE name='run'"
        ).fetchone()[0]
        assert results[0][0] == entity_id
        assert connection.execute("SELECT COUNT(*) FROM lexical").fetchone()[0] == 1


def test_refresh_replaces_and_deletes_lexical_rows(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "app.py"
    source.write_text('def run():\n    """oldquasar"""\n    return 1\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    summary = build(root, Provider())
    refresh(root, Provider())

    source.write_text('def run():\n    """newnebula"""\n    return 2\n')
    refresh(root, Provider())
    with sqlite3.connect(summary.db_path) as connection:
        assert lexical_search(connection, "oldquasar", 10) == []
        assert len(lexical_search(connection, "newnebula", 10)) == 1

    source.unlink()
    refresh(root, Provider())
    with sqlite3.connect(summary.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM lexical").fetchone()[0] == 0


def test_lexical_search_returns_empty_without_fts_table():
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE entities(id INTEGER)")
        assert lexical_search(connection, "anything", 10) == []


def test_lexical_search_ors_filtered_natural_language_terms():
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE VIRTUAL TABLE lexical USING fts5(name, doc, body)")
        connection.execute(
            "INSERT INTO lexical(rowid,name,doc,body) VALUES "
            "(1,'predict','', 'lunar eclipses'), (2,'calculate','','tidal harmonics')"
        )
        results = lexical_search(connection, "Where is lunar and how does it work?", 10)
        assert [row[0] for row in results] == [1]
