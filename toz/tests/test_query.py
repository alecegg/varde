import json

import blake3
from varde_toz.chunk import chunk_default
from varde_toz.commands import query
from varde_toz.project import store_db_path
from varde_toz.raw import RawStore
from varde_toz.store import NewCapture, Store


def _capture(store, label="fixture", body="needle in this output\n", *, indexed=True):
    chunks = [("stdout", chunk) for chunk in chunk_default(body)]
    return store.insert_capture(
        NewCapture(label=label, kind="run", source=label, bytes=len(body), exit_code=0),
        chunks,
        indexed=indexed,
    )


def _project(tmp_path, monkeypatch):
    """Point the query command at a temporary project store."""
    root = tmp_path / "repo"
    base = tmp_path / "toz"
    root.mkdir()
    base.mkdir()
    monkeypatch.setenv("TOZ_PROJECT", str(root))
    monkeypatch.setenv("TOZ_CONFIG_DIR", str(base))
    path = store_db_path(root, base)
    return root, path


def test_search_indexes_deferred_captures(tmp_path):
    store = Store.open(tmp_path / "toz.db")
    try:
        handle = _capture(store, indexed=False)
        assert store.index_deferred(handle) == 1
        assert store.search('"needle"')
    finally:
        store.close()


def test_search_refreshes_changed_indexed_file(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    source = tmp_path / "indexed.txt"
    source.write_text("old marker\n")
    data = source.read_bytes()
    store = Store.open(path)
    store.insert_capture(
        NewCapture(
            label="indexed",
            kind="index",
            source=str(source),
            source_key="indexed",
            bytes=len(data),
            exit_code=0,
            file_mtime=source.stat().st_mtime_ns,
            file_hash=blake3.blake3(data).digest(),
        ),
        [("stdout", chunk) for chunk in chunk_default(data.decode())],
    )
    source.write_text("fresh marker\n")
    store.close()
    assert query.main(["fresh", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result[0]["hits"][0]["label"] == "indexed"


def test_handle_lookup_searches_fallback_stores(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    fallback = tmp_path / "fallback"
    (fallback / "other").mkdir(parents=True)
    monkeypatch.setenv("TOZ_FALLBACK_DIR", str(fallback))
    store = Store.open(fallback / "other" / "toz.db")
    handle = _capture(store, body="fallback body\n")
    store.close()
    assert not path.exists()
    assert query.main(["--handle", handle]) == 0
    assert "fallback body" in capsys.readouterr().out


def test_raw_lookup_searches_fallback_store(tmp_path, monkeypatch, capsysbinary):
    _root, path = _project(tmp_path, monkeypatch)
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    monkeypatch.setenv("TOZ_FALLBACK_DIR", str(fallback))
    raw = RawStore(fallback / "raw", enabled=True)
    handle = raw.store("key", b"exact bytes")
    assert not path.exists()
    assert query.main(["--raw", str(handle)]) == 0
    assert capsysbinary.readouterr().out == b"exact bytes"


def test_limit_zero_is_not_replaced_by_default(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    store = Store.open(path)
    _capture(store)
    store.close()
    assert query.main(["--list", "--limit", "0", "--json"]) == 0
    assert capsys.readouterr().out == "[]\n"


def test_search_limit_zero_clamps_to_one_result(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    store = Store.open(path)
    _capture(store, label="first", body="needle alpha\n")
    _capture(store, label="second", body="needle beta\n")
    store.close()
    assert query.main(["--limit", "0", "needle", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)[0]["hits"]) == 1


def test_text_list_includes_age_and_superseded_marker(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    store = Store.open(path)
    _capture(store)
    store.close()
    assert query.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "chunks" in output and "ago" in output and "fixture" in output


def test_chunk_json_uses_sorted_rust_key_order(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    store = Store.open(path)
    handle = _capture(store)
    store.close()
    assert query.main(["--handle", handle, "--chunk", "0", "--json"]) == 0
    output = capsys.readouterr().out
    assert list(json.loads(output)) == [
        "body",
        "chunk",
        "handle",
        "line_end",
        "line_start",
        "stream",
        "title",
    ]


def test_empty_store_search_json_is_empty_array(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    assert not path.exists()
    assert query.main(["needle", "--json"]) == 0
    assert capsys.readouterr().out == "[]\n"


def test_search_records_query_event(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    store = Store.open(path)
    _capture(store)
    store.close()
    assert query.main(["needle", "--json"]) == 0
    capsys.readouterr()
    with Store.open_readonly(path) as store:
        row = store.conn.execute(
            "SELECT kind,outcome,details_json FROM query_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "search" and row[1] == "ok"
    assert json.loads(row[2])["query_count"] == 1


def test_sqlite_errors_are_cli_errors(tmp_path, monkeypatch, capsys):
    _root, path = _project(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a database")
    assert query.main(["--list"]) == 2
    assert "varde-toz:" in capsys.readouterr().err


def test_foreign_handle_error_explains_project_scope(tmp_path, monkeypatch, capsys):
    _root, current_path = _project(tmp_path, monkeypatch)
    foreign = Store.open(tmp_path / "foreign" / "toz.db")
    handle = _capture(foreign, body="foreign project body\n")
    foreign.close()

    assert not current_path.exists()
    assert query.main(["--handle", handle]) == 2

    assert "handles are project-scoped" in capsys.readouterr().err
