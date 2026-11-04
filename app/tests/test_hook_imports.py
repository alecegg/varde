import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from varde import cli
from varde.fastpath import run

ROOT = Path(__file__).resolve().parents[2]


def test_hook_fastpath_calls_toz_without_discovering_modules(monkeypatch, capsys):
    monkeypatch.setattr("varde_toz.cli.main", lambda argv: print(argv) or 0)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )
    monkeypatch.setattr(
        cli,
        "signal",
        SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *args: None),
    )

    assert cli.main(["capture", "--hook", "--harness", "pi"]) == 0
    assert capsys.readouterr().out == "['capture', '--hook', '--harness', 'pi']\n"


def test_hook_subprocess_does_not_import_app_packages():
    script = """
import sys
from types import ModuleType

stub = ModuleType('varde_toz.cli')
stub.main = lambda argv: 0
sys.modules['varde_toz.cli'] = stub
from varde import cli
assert cli.main(['capture', '--hook', '--harness', 'pi']) == 0
blocked = {'importlib.metadata', 'sqlite3'}
blocked.update(
    name for name in sys.modules
    if name.startswith('varde_') and not name.startswith('varde_toz')
)
present = sorted(blocked.intersection(sys.modules))
assert not present, present
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (
            str(ROOT / "app/src"),
            str(ROOT / "toz/src"),
        )
    )
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True)  # noqa: S603 - Checks hook imports in a clean interpreter process.


def test_fastpath_handles_note_and_event(monkeypatch, capsys):
    monkeypatch.setattr("varde_toz.cli.main", lambda argv: print(argv) or 3)

    assert run(["note", "--harness", "pi"]) == 3
    assert run(["event", "--harness", "pi"]) == 3
    assert capsys.readouterr().out == (
        "['note', '--harness', 'pi']\n['event', '--harness', 'pi']\n"
    )


def test_fastpath_leaves_other_capture_commands_to_router():
    assert run(["capture", "--force"]) is None
    assert run(["map", "nav_map"]) is None
