from pathlib import Path

from varde_code.index.paths import repo_db_path


def test_repo_db_path_name_is_stable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path))
    path = repo_db_path(Path("/nonexistent/varde-pin"))
    assert path == tmp_path / "code/repos-py/varde-pin-3296efbb01fd95ae/index.db"
