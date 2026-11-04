import importlib

from varde_dev.calibrate import cli


def test_unbuilt_command_reports_unavailable(capsys, monkeypatch):
    group = "future"
    monkeypatch.setattr(cli, "COMMANDS", (*cli.COMMANDS, group))

    def missing_group(module_name):
        raise ModuleNotFoundError(
            f"No module named '{module_name}'",
            name=f"varde_dev.calibrate.{group}",
        )

    monkeypatch.setattr(importlib, "import_module", missing_group)
    result = cli.main([group])

    assert result == 2
    assert f"calibrate {group}: not yet available" in capsys.readouterr().err
