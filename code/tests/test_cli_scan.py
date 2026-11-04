from __future__ import annotations

import json

from varde_code import cli_scan, module


def test_module_dispatches_scan_run(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        cli_scan,
        "scan_repo",
        lambda value, capture=None: {"gate": {"status": "pass"}, "value": value},
    )

    code = module.register().run(
        ["scan", "--json", json.dumps({"repoRoot": str(tmp_path)})]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["data"]["value"]["repoRoot"] == str(
        tmp_path
    )


def test_module_dispatches_edit(monkeypatch):
    from varde_code import cli_edit

    called = []
    monkeypatch.setattr(cli_edit, "run", lambda argv, io=None: called.append(argv) or 7)

    assert module.register().run(["edit", "preview"]) == 7
    assert called == [["edit", "preview"]]


def test_scan_no_argument_reports_missing_json(capsys):
    assert module.register().run(["scan"]) == 2
    output = capsys.readouterr()
    assert "--json <JSON>" in output.err
    assert output.out == ""


def test_edit_help_snapshots_cover_preview_and_apply():
    from varde_code import cli_edit

    assert "Usage: varde edit preview" in cli_edit.help("preview")
    assert "Usage: varde edit apply" in cli_edit.help("apply")


def test_scan_nested_help_and_missing_json_use_rust_cli_contract(capsys):
    assert module.register().run(["scan", "rules", "list", "--help"]) == 0
    assert "Usage: varde scan rules rules_list" in capsys.readouterr().out


def test_scan_invalid_json_uses_legacy_error_envelope(capsys):
    assert module.register().run(["scan", "--json", "{"]) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["data"]["error"]["message"] == (
        "input is not valid JSON: EOF while parsing an object at line 1 column 1"
    )
    assert "envelope_version" not in value


def test_setup_and_rules_results_use_success_envelope(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli_scan.setup, "run", lambda value: {"preset": "balanced"})
    monkeypatch.setattr(
        cli_scan.rules_cmd, "run", lambda *args, **kwargs: {"rules": []}
    )

    assert (
        module.register().run(
            [
                "scan",
                "setup",
                "--json",
                json.dumps({"repoRoot": str(tmp_path), "preset": "balanced"}),
            ]
        )
        == 0
    )
    setup_output = capsys.readouterr().out
    assert setup_output == (
        '{"data":{"preset":"balanced"},"meta":{"compact":true,'
        '"truncated":false},"ok":true,"outcome":"success",'
        '"schema_version":1}\n'
    )

    assert (
        module.register().run(
            ["scan", "rules", "list", "--json", json.dumps({"repoRoot": str(tmp_path)})]
        )
        == 0
    )
    rules_output = capsys.readouterr().out
    assert rules_output == (
        '{"data":{"rules":[]},"meta":{"compact":true,'
        '"truncated":false},"ok":true,"outcome":"success",'
        '"schema_version":1}\n'
    )


def test_edit_help_and_invalid_arguments_use_clap_contract(capsys):
    from pathlib import Path

    from varde_code.ast_edit import cli as edit_cli
    from varde_code.ast_edit.cli import Options

    assert module.register().run(["edit", "preview", "--help"]) == 0
    assert "Usage: varde edit preview" in capsys.readouterr().out
    options = Options(Path.cwd(), Path.cwd())
    assert (
        edit_cli.run(["edit", "preview", "--json", "{}"], io=None, options=options) == 2
    )
    assert "unexpected argument '{}' found" in capsys.readouterr().err


def test_scan_help_names_report_flags():
    text = cli_scan.help("run")
    for flag in ("--report", "--no-build", "--repo-root", "--readme-max-behind"):
        assert flag in text
