from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from varde_code import cli_index


def test_resolver_uses_community_detection_to_split_tightly_connected_groups():
    from varde_code.index.resolve import resolve

    files = [f"{name}.py" for name in "abcdef"]
    links = [(0, 1), (0, 2), (1, 2), (3, 4), (3, 5), (4, 5), (2, 3)]
    entities = [
        {"file_id": source, "kind": "import", "name": f"./{files[target][:-3]}"}
        for source, target in links
    ]

    result = resolve(entities, [], files)

    assert result["communities"] == [
        {"id": 0, "members": ["a.py", "b.py", "c.py"]},
        {"id": 1, "members": ["d.py", "e.py", "f.py"]},
    ]


def test_full_build_resolves_relative_python_import_and_starts_at_revision_zero(
    tmp_path, monkeypatch
):
    from varde_code.extract.provider import CodeExtractionProvider
    from varde_code.index.build import build
    from varde_code.model import EntityKind

    root = tmp_path / "repo"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "app.py").write_text(
        "from .helper import render\n\n\ndef main(name):\n    return render(name)\n",
        encoding="utf-8",
    )
    (source / "helper.py").write_text(
        "def render(name):\n    return name\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    try:
        CodeExtractionProvider().extract(
            source / "app.py", "from .helper import render\n", "python"
        )
    except RuntimeError as exc:
        if "Could not load the python grammar" in str(exc):
            pytest.skip(
                "Python tree-sitter grammar is unavailable in the configured cache"
            )
        raise

    summary = build(root, CodeExtractionProvider())

    with sqlite3.connect(summary.db_path) as connection:
        assert connection.execute(
            "SELECT edge.resolved,target.path FROM resolved_edges AS edge "
            "JOIN files AS source ON source.id=edge.from_file_id "
            "LEFT JOIN files AS target ON target.id=edge.to_file_id "
            "JOIN entities AS entity ON entity.id=edge.from_entity_id "
            "WHERE source.path=? AND entity.kind=?",
            (str(source / "app.py"), EntityKind.IMPORT.value),
        ).fetchone() == (1, str(source / "helper.py"))
        assert connection.execute(
            "SELECT source.community_id=target.community_id FROM files AS source "
            "JOIN files AS target ON target.path=? WHERE source.path=?",
            (str(source / "helper.py"), str(source / "app.py")),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT value FROM slice_meta WHERE key='next_rev'"
        ).fetchone() == (0,)


def test_map_build_emits_result_with_relative_changed_paths(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("pass\n", encoding="utf-8")
    changed = (str(root / "main.py"),)
    monkeypatch.setattr(cli_index, "_index_exists", lambda repo: False)
    monkeypatch.setattr(
        "varde_code.index.build.build",
        lambda repo, extractor: SimpleNamespace(
            db_path="/config/code/repos-py/repo/index.db",
            entities=3,
            symbols=2,
            diagnostics=0,
            changed_files=changed,
        ),
    )

    status = cli_index.register().run(
        ["map", "build", "--repo-root", str(root)],
        SimpleNamespace(extractor=object()),
    )

    assert status == 0
    assert capsys.readouterr().out == (
        '{"data":{"changedFilesCount":1,"changedFilesSample":["main.py"],'
        '"dbPath":"/config/code/repos-py/repo/index.db","diagnostics":0,'
        '"entities":3,"reparsed":1,"symbols":2,"unchanged":0},'
        '"meta":{"compact":true,"truncated":false},"ok":true,'
        '"outcome":"success","schema_version":1}\n'
    )
