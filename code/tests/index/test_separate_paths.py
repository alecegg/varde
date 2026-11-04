from __future__ import annotations

from varde_code.index.paths import repo_db_path


def test_rust_and_python_index_paths_are_separate(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    python_path = repo_db_path(root)
    rust_path = (
        tmp_path / "config" / "code" / "repos" / python_path.parent.name / "index.db"
    )

    assert python_path.parent.parent == tmp_path / "config" / "code" / "repos-py"
    assert rust_path.parent.parent == tmp_path / "config" / "code" / "repos"
    assert python_path != rust_path
