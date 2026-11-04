from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from varde_code import cli_index
from varde_code.model import ExtractOutput
from varde_code.module import register as register_module


class _EmptyExtractor:
    def extract(self, path: Path, source: str, language: str) -> ExtractOutput:
        return ExtractOutput()


def test_module_routes_index_commands_and_keeps_query_lazy(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli_index,
        "register",
        type(
            "Index",
            (),
            {"run": lambda self, argv, io: calls.append(("index", argv, io)) or 7},
        ),
    )

    result = register_module().run(["map", "build", "--repo-root", "."], object())

    assert result == 7
    assert calls[0][0:2] == ("index", ["map", "build", "--repo-root", "."])


def test_module_keeps_query_route_and_routes_watch(monkeypatch, capsys):
    monkeypatch.setattr("varde_code.cli_query.run", lambda argv, io: 5)

    assert register_module().run(["map", "symbols_in_file"], None) == 5
    assert register_module().run(["watch"], None) == 2
    assert "setup watch requires at least one --repo" in capsys.readouterr().err
    assert register_module().run(["unsupported"], None) == 2
    assert "code: module stub" in capsys.readouterr().err


def test_help_snapshots_are_read_verbatim():
    assert (
        cli_index.register()
        .help("map build")
        .startswith("Extract, resolve, and persist")
    )
    assert "Usage: varde map prune" in cli_index.register().help("map prune")
    assert "Usage: varde setup watch" in cli_index.register().help("setup watch")


def test_prune_dispatches_json_and_prints_result(monkeypatch, capsys):
    monkeypatch.setattr(
        "varde_code.index.prune.run", lambda value: {"apply": value["apply"]}
    )

    status = cli_index.register().run(["map", "prune", "--json", '{"apply":true}'])

    assert status == 0
    assert capsys.readouterr().out == '{"apply":true}\n'


def test_invalid_prune_json_returns_cli_error(capsys):
    status = cli_index.register().run(["map", "prune", "--json", "{"])

    assert status == 2
    assert "invalid --json" in capsys.readouterr().err


def test_map_build_creates_index_and_reports_changed_files(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    status = cli_index.register().run(
        ["map", "build", "--repo-root", str(repo), "--changed-files"],
        SimpleNamespace(extractor=_EmptyExtractor()),
    )

    assert status == 0
    assert '"changedFilesCount":1' in capsys.readouterr().out
    assert list((tmp_path / "config" / "code" / "repos-py").rglob("index.db"))


def test_map_build_uses_registered_extractor_when_io_is_none(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(cli_index, "_extraction_provider", None)
    cli_index.register_extraction_provider(_EmptyExtractor())

    status = cli_index.register().run(["map", "build", "--repo-root", str(repo)])

    assert status == 0
    assert '"entities":0' in capsys.readouterr().out
    assert list((tmp_path / "config" / "code" / "repos-py").rglob("index.db"))


def test_module_import_does_not_load_index_or_parser(monkeypatch):
    monkeypatch.delitem(sys.modules, "varde_code.index", raising=False)
    monkeypatch.delitem(sys.modules, "varde_code.parse", raising=False)

    cli_index.register()

    assert "varde_code.index" not in sys.modules
    assert "varde_code.parse" not in sys.modules


def test_watch_list_and_stop_all_return_empty_success_results(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    status = cli_index.register().run(["setup", "watch", "--list"])
    assert status == 0
    assert capsys.readouterr().out == (
        '{"data":[],"meta":{"compact":false,"truncated":false},'
        '"ok":true,"outcome":"success","schema_version":1}\n'
    )

    status = cli_index.register().run(["setup", "watch", "--stop-all"])
    assert status == 0
    assert capsys.readouterr().out == (
        '{"data":[],"meta":{"compact":false,"truncated":false},'
        '"ok":true,"outcome":"success","schema_version":1}\n'
    )


def test_watch_config_resolves_repo_for_stop(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    config = tmp_path / "watch.toml"
    config.write_text(f'repos = ["{repo}"]\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    status = cli_index.register().run(
        ["setup", "watch", "--config", str(config), "--stop"]
    )

    assert status == 1
    output = capsys.readouterr().out
    assert '"code":"watch_error"' in output
    assert "no watcher lock found for this repo set" in output


def test_watch_remove_index_removes_python_index_even_if_stop_fails(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    from varde_code.index.paths import repo_db_path

    db = repo_db_path(repo)
    db.parent.mkdir(parents=True)
    db.write_bytes(b"index")
    db.with_name("source-root").write_text(str(repo), encoding="utf-8")

    status = cli_index.register().run(
        ["setup", "watch", "--repo", str(repo), "--stop", "--remove-index"]
    )

    assert status == 1
    assert not db.exists()
    assert not db.with_name("source-root").exists()
    assert '"code":"watch_error"' in capsys.readouterr().out


def test_watch_remove_index_rejects_config(tmp_path, capsys):
    status = cli_index.register().run(
        [
            "setup",
            "watch",
            "--config",
            str(tmp_path / "watch.toml"),
            "--stop",
            "--remove-index",
        ]
    )

    assert status == 1
    assert capsys.readouterr().out == (
        '{"data":{"error":{"code":"invalid_input",'
        '"message":"--stop --remove-index requires exactly one --repo '
        'and no --config"}},'
        '"meta":{"compact":false,"truncated":false},"ok":false,'
        '"outcome":"tool-error","schema_version":1}\n'
    )


def test_setup_watch_route_registers_extraction_provider(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli_index, "_extraction_provider", None)
    monkeypatch.setattr(
        "varde_code.index.watch.run_foreground",
        lambda repos, service, debounce: seen.append((repos, debounce)),
    )

    status = register_module().run(["setup", "watch", "--repo", str(tmp_path)], None)

    assert status == 0
    assert len(seen) == 1
    assert cli_index._extraction_provider is not None
