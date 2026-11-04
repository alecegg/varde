from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from varde import cli

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_learn_store(monkeypatch, tmp_path):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))


@pytest.fixture
def cli_runtime(monkeypatch):
    for name in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_SESSION_ID",
        "CODEX_THREAD_ID",
        "VARDE_TOZ_SESSION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    module = type("Module", (), {"run": lambda self, argv, io: 0})()
    monkeypatch.setattr(cli, "_discover_modules", lambda: {"code": module})
    monkeypatch.setattr(cli, "_create_io", lambda: None)
    rows = []

    def append(row):
        rows.append(row)
        return True

    monkeypatch.setattr("varde_learn.loop.calls.append_call", append)
    return rows


def test_records_success(cli_runtime):
    rows = cli_runtime

    assert cli.main(["map", "nav_map"]) == 0
    assert len(rows) == 1
    assert rows[0]["command"] == "map"
    assert rows[0]["status"] == "success"
    assert rows[0]["duration_s"] >= 0
    assert rows[0]["session"] is None


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["learn", "how", "varde-docs", "audit"], "varde-docs/audit"),
        (["learn", "how", "--json", "varde-docs", "audit"], "varde-docs/audit"),
        (["learn", "how", "varde-docs"], None),
        (["learn", "how", "Varde Docs", "audit"], None),
        (["learn", "how", "varde-docs", "au/dit"], None),
        (["learn", "how", "varde-docs", "audit", "extra"], None),
    ],
)
def test_learn_how_records_validated_topic_arg(
    cli_runtime, monkeypatch, args, expected
):
    rows = cli_runtime
    module = type("Module", (), {"run": lambda self, argv, io: 0})()
    monkeypatch.setattr(cli, "_discover_modules", lambda: {"learn": module})

    assert cli.main(args) == 0
    assert rows[0].get("arg") == expected
    assert ("arg" in rows[0]) == (expected is not None)


def test_other_commands_record_no_arg(cli_runtime):
    assert cli.main(["map", "nav_map"]) == 0
    assert "arg" not in cli_runtime[0]


def test_records_failure(cli_runtime, monkeypatch):
    rows = cli_runtime
    monkeypatch.setattr(
        cli,
        "_discover_modules",
        lambda: {"code": type("Module", (), {"run": lambda *args: 3})()},
    )

    assert cli.main(["map", "nav_map"]) == 3
    assert rows[0]["status"] == "failure"


def test_setup_route_gets_subcommand_name(cli_runtime, monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "varde.setup.dispatch",
        SimpleNamespace(run_setup_route=lambda args: 1),
    )
    cli.main(["setup", "doctor"])
    assert cli_runtime[0]["command"] == "setup doctor"


@pytest.mark.parametrize(
    ("path", "args", "module", "expected"),
    [
        (
            ("plan",),
            ["plan", "task", "set", "task.md", "done"],
            "workflow",
            "plan task set",
        ),
        (
            ("learn",),
            ["learn", "friction", "add", "--title", "plan"],
            "learn",
            "learn friction add",
        ),
        (
            ("learn",),
            ["learn", "sessions", "summary", "--repository", "."],
            "learn",
            "learn sessions summary",
        ),
        (
            ("learn",),
            ["learn", "friction", "adopt", "--summary", "done"],
            "learn",
            "learn friction adopt",
        ),
        (
            ("learn",),
            ["learn", "measure", "skills/example", "calibrate"],
            "learn",
            "learn measure",
        ),
        (("plan",), ["plan", "merged", "plan.md"], "workflow", "plan merged"),
        (
            ("plan",),
            ["plan", "approve-merge", "plan.md"],
            "workflow",
            "plan approve-merge",
        ),
    ],
)
def test_records_longest_validated_nested_command(path, args, module, expected):
    if module == "workflow":
        from varde_workflow.cli import help_text
    else:
        from varde_learn.loop.help import help_text

    assert (
        cli._recorded_route(path, args, help_text(" ".join(path)), help_text)
        == expected
    )


def test_recorded_route_ignores_module_help_errors():
    def broken_help(_command: str) -> str:
        raise ValueError

    assert cli._recorded_route(("plan",), ["plan", "broken"], "", broken_help) == "plan"


def test_learn_guardrails_fire_skips_entrypoint_row(monkeypatch):
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    monkeypatch.setattr(
        cli,
        "_discover_modules",
        lambda: {"learn": type("Module", (), {"run": lambda *args: 0})()},
    )
    rows = []
    monkeypatch.setattr(
        "varde_learn.loop.calls.append_call", lambda row: rows.append(row) or True
    )
    assert cli.main(["learn", "sessions", "fire", "g"]) == 0
    assert rows == []


def test_records_exception_and_reraises(cli_runtime, monkeypatch):
    rows = cli_runtime
    error = RuntimeError("command failed")
    monkeypatch.setattr(
        cli,
        "_discover_modules",
        lambda: {
            "code": type(
                "Module", (), {"run": lambda *args: (_ for _ in ()).throw(error)}
            )()
        },
    )

    with pytest.raises(RuntimeError, match="command failed"):
        cli.main(["map", "nav_map"])
    assert rows[0]["status"] == "failure"


@pytest.mark.parametrize(
    ("code", "expected"), [(None, "success"), (0, "success"), (2, "failure")]
)
def test_records_system_exit_code(cli_runtime, monkeypatch, code, expected):
    rows = cli_runtime
    monkeypatch.setattr(
        cli,
        "_discover_modules",
        lambda: {
            "code": type(
                "Module",
                (),
                {"run": lambda *args: (_ for _ in ()).throw(SystemExit(code))},
            )()
        },
    )

    with pytest.raises(SystemExit) as error:
        cli.main(["map", "nav_map"])
    assert error.value.code == code
    assert rows[0]["status"] == expected


def test_records_keyboard_interrupt_and_reraises(cli_runtime, monkeypatch):
    rows = cli_runtime
    monkeypatch.setattr(
        cli,
        "_discover_modules",
        lambda: {
            "code": type(
                "Module",
                (),
                {"run": lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())},
            )()
        },
    )

    with pytest.raises(KeyboardInterrupt):
        cli.main(["map", "nav_map"])
    assert rows[0]["status"] == "failure"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {
                "CLAUDE_SESSION_ID": "claude",
                "CODEX_THREAD_ID": "codex",
                "VARDE_TOZ_SESSION": "toz",
            },
            "claude",
        ),
        ({"CODEX_THREAD_ID": "codex", "VARDE_TOZ_SESSION": "toz"}, "codex"),
        ({"VARDE_TOZ_SESSION": "toz"}, "toz"),
        ({"CLAUDE_SESSION_ID": "", "CODEX_THREAD_ID": "codex"}, "codex"),
    ],
)
def test_session_environment_precedence(cli_runtime, monkeypatch, values, expected):
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    cli.main(["map", "nav_map"])

    assert cli_runtime[0]["session"] == expected


def test_store_failure_does_not_change_exit_or_output(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    monkeypatch.setattr(cli, "_discover_modules", dict)
    monkeypatch.setattr(
        "varde_learn.loop.calls.append_call",
        lambda row: (_ for _ in ()).throw(OSError("store unavailable")),
    )

    assert cli.main(["nonsense"]) == 2
    assert capsys.readouterr().err.startswith(
        "error: unrecognized subcommand 'nonsense'"
    )


@pytest.mark.parametrize(
    ("args", "command"),
    [
        ([], "help"),
        (["help"], "help"),
        (["--help"], "help"),
        (["map", "--help"], "help"),
        (["-V"], "version"),
        (["--version"], "version"),
        (["nonsense", "--token=SECRET"], "unknown"),
    ],
)
def test_fastpaths_and_unknown_commands_are_safely_named(cli_runtime, args, command):
    rows = cli_runtime
    cli.main(args)
    assert len(rows) == 1
    assert rows[0]["command"] == command
    assert "SECRET" not in str(rows)


def test_real_store_failure_does_not_change_output_or_status(
    monkeypatch, capsys, tmp_path
):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file")
    monkeypatch.setenv("VARDE_LEARN_STORE", str(blocked / "learn"))
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    monkeypatch.setattr(cli, "_discover_modules", dict)

    assert cli.main(["nonsense"]) == 2
    assert capsys.readouterr().err.startswith(
        "error: unrecognized subcommand 'nonsense'"
    )


def test_real_plan_subcommands_record_and_match_shipped_guardrails(
    monkeypatch, tmp_path, capsys
):
    from varde_learn.loop.calls import read_calls
    from varde_learn.loop.guardrails import firings, load_registry

    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    cli.main(["plan", "gate", "--help"])
    cli.main(["plan", "validate", "missing-artifact"])
    capsys.readouterr()

    rows = read_calls(tmp_path / "learn")
    assert [row["command"] for row in rows] == ["plan gate", "plan validate"]
    counts = firings(load_registry(), rows)
    assert counts["plan-gate"]["fired"] == 1
    assert counts["plan-validate"]["blocked"] == 1


def test_setup_flags_record_bare_route_without_secret(monkeypatch, tmp_path, capsys):
    from varde_learn.loop.calls import read_calls

    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    cli.main(["setup", "--token=SECRET123"])
    capsys.readouterr()

    rows = read_calls(tmp_path / "learn")
    assert len(rows) == 1
    assert rows[0]["command"] == "setup"
    assert "SECRET123" not in str(rows)


def test_recording_does_not_swallow_system_exit(monkeypatch):
    monkeypatch.setattr(
        "varde_learn.loop.calls.append_call",
        lambda row: (_ for _ in ()).throw(SystemExit(7)),
    )
    with pytest.raises(SystemExit) as error:
        cli._record_call("map", 0, 0)
    assert error.value.code == 7


def test_import_failure_does_not_change_cli_result(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "varde_learn.loop.calls":
            raise ImportError("learn package unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signal",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *args: None)},
        ),
    )

    assert cli.main(["--version"]) == 0


def test_broken_pipe_records_success(cli_runtime, monkeypatch):
    class Closed:
        def write(self, value):
            raise BrokenPipeError

        def close(self):
            pass

    monkeypatch.setattr(cli.sys, "stdout", Closed())

    assert cli.main(["--help"]) == 0
    assert cli_runtime[0]["command"] == "help"
    assert cli_runtime[0]["status"] == "success"


def test_fastpath_does_not_record_or_import_learn(tmp_path):
    script = """
import sys
from types import ModuleType

stub = ModuleType('varde_toz.cli')
stub.main = lambda argv: 0
sys.modules['varde_toz.cli'] = stub
from varde import cli
assert cli.main(['capture', '--hook', '--harness', 'pi']) == 0
assert not any(name.startswith('varde_learn') for name in sys.modules)
"""
    env = os.environ.copy()
    env["VARDE_LEARN_STORE"] = str(tmp_path / "learn")
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "app/src"), str(ROOT / "toz/src")))

    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True)  # noqa: S603 - test launches an isolated Python process
    assert not (tmp_path / "learn" / "cli_calls.jsonl").exists()
