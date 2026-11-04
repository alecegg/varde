import json
from pathlib import Path
from types import SimpleNamespace

from varde import cli


def test_setup_doctor_reports_the_hooks_section(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "signal", SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *args: None)
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))

    status = cli.main(["setup", "doctor", "--json"])

    report = json.loads(capsys.readouterr().out)
    hooks = report["hooks"]
    assert {entry["target"] for entry in hooks} >= {"SessionStart", "Stop"}
    assert all(entry["state"] for entry in hooks)
    assert status in (0, 1)
