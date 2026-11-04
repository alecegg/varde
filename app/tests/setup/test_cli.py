from types import SimpleNamespace

from varde import cli
from varde.io import create_io
from varde.setup import dispatch
from varde.setup.module import register


def test_setup_help_reports_usage_and_actions(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "signal", SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *args: None)
    )
    for args, fragments in (
        (["setup", "sync", "--help"], ("Usage:", "--dry-run")),
        (["setup", "hooks", "install", "--help"], ("Usage:", "--harness")),
        (["setup", "hooks", "remove", "--help"], ("Usage:", "--harness")),
    ):
        assert cli.main(args) == 0
        output = capsys.readouterr().out
        for fragment in fragments:
            assert fragment in output


def test_setup_route_handles_help_and_leaves_doctor_to_the_cli(capsys):
    assert dispatch.run_setup_route(["setup", "sync", "--help"]) == 0
    assert "Usage:" in capsys.readouterr().out
    assert dispatch.run_setup_route(["setup", "hooks", "remove", "--help"]) == 0
    assert "Usage:" in capsys.readouterr().out
    assert dispatch.run_setup_route(["setup", "doctor"]) is None


def test_autosave_module_reports_help_and_strips_command_prefix(capsys):
    module = register()
    assert module.name == "autosave"
    assert "Usage:" in module.help("setup autosave")

    assert module.run(["varde setup autosave", "--help"], create_io()) == 0

    assert "usage:" in capsys.readouterr().out.lower()
