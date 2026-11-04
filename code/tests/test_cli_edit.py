from __future__ import annotations

from pathlib import Path

from varde_code import cli_edit


def test_proposal_store_uses_builtin_config_directory(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(cli_edit, "varde_config_dir", lambda: config)
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    _assert_preview_writes_to(monkeypatch, tmp_path / "repo", config / "ast-edit")


def test_proposal_store_uses_project_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text(f'[project."{root}"]\nworking = "work"\n')
    monkeypatch.setattr(cli_edit, "varde_config_dir", lambda: config)
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    _assert_preview_writes_to(monkeypatch, root, root / "work" / "ast-edit")


def test_proposal_store_environment_overrides_project_config(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text(f'[project."{root}"]\nworking = "work"\n')
    monkeypatch.setattr(cli_edit, "varde_config_dir", lambda: config)
    monkeypatch.setenv("VARDE_WORKING_DIR", "override")
    _assert_preview_writes_to(monkeypatch, root, root / "override" / "ast-edit")


def _assert_preview_writes_to(monkeypatch, repository: Path, store: Path) -> None:
    repository.mkdir(parents=True, exist_ok=True)

    def write_preview(_args, _io, options):
        options.store_dir.mkdir(parents=True, exist_ok=True)
        (options.store_dir / "preview.json").write_text("{}")
        return 0

    monkeypatch.chdir(repository)
    monkeypatch.setattr(cli_edit, "run_ast_edit", write_preview)

    assert cli_edit.run(["preview"]) == 0
    assert (store / "preview.json").read_text() == "{}"
