from types import SimpleNamespace

from varde import cli


def _patch_signal(monkeypatch):
    monkeypatch.setattr(
        cli,
        "signal",
        SimpleNamespace(SIGPIPE=1, SIG_IGN=0, signal=lambda *args: None),
    )


def test_root_help_lists_public_commands(monkeypatch, capsys):
    _patch_signal(monkeypatch)

    assert cli.main(["--help"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("Code maps")
    assert "Usage: varde" in output
    for command in ("map", "scan", "plan", "setup", "help"):
        assert command in output


def test_root_help_word_matches_help_flag(monkeypatch, capsys):
    _patch_signal(monkeypatch)

    assert cli.main(["help"]) == 0
    assert "Usage: varde" in capsys.readouterr().out


def test_empty_invocation_prints_root_help(monkeypatch, capsys):
    _patch_signal(monkeypatch)

    assert cli.main([]) == 0
    assert "Usage: varde" in capsys.readouterr().out


def test_version_prints_version_without_discovering_modules(monkeypatch, capsys):
    _patch_signal(monkeypatch)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )

    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("varde ")

    assert cli.main(["-V"]) == 0
    assert capsys.readouterr().out.startswith("varde ")


def test_help_word_in_command_arguments_is_not_root_help(monkeypatch, capsys):
    _patch_signal(monkeypatch)

    class Module:
        def run(self, args, io):
            print(args[-1])
            return 0

    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: {"workflow": Module(), "code": Module()},
    )

    assert cli.main(["msg", "send", "--to", "main", "--kind", "info", "help"]) == 0
    assert cli.main(["map", "nav_map", "--query", "help"]) == 0
    assert capsys.readouterr().out == "help\nhelp\n"


def test_help_flag_must_follow_a_resolved_route(monkeypatch, capsys):
    _patch_signal(monkeypatch)

    class Module:
        def run(self, args, io):
            print(args[-2:])
            return 0

    monkeypatch.setattr("varde.discovery.discover_modules", lambda: {"code": Module()})

    assert cli.main(["map", "nav_map", "--help", "extra"]) == 0
    assert capsys.readouterr().out == "['--help', 'extra']\n"


def test_route_help_uses_snapshot_without_discovering_modules(monkeypatch, capsys):
    _patch_signal(monkeypatch)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )

    assert cli.main(["map", "--help"]) == 0
    assert capsys.readouterr().out.startswith(
        "Query the code index (symbols, dependencies, impact)\n"
    )


def test_plan_help_snapshot_lists_task_status_command(monkeypatch, capsys):
    _patch_signal(monkeypatch)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )

    assert cli.main(["plan", "--help"]) == 0
    output = capsys.readouterr().out
    assert (
        "task set              Change a task status using the workflow transitions"
        in output
    )


def test_learn_help_snapshot_lists_sessions_and_measure(monkeypatch, capsys):
    _patch_signal(monkeypatch)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )
    assert cli.main(["learn", "--help"]) == 0
    output = capsys.readouterr().out
    assert (
        "sessions   Inspect, summarize, sweep and review local agent sessions" in output
    )
    assert "measure    Measure a skill" in output


def test_learn_help_snapshot_lists_docs_commands(monkeypatch, capsys):
    _patch_signal(monkeypatch)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )
    assert cli.main(["learn", "--help"]) == 0
    output = capsys.readouterr().out
    assert "  skills " in output
    assert (
        "  memory     Scoped agent, skill, project and global memory entries" in output
    )
    assert "  how  " in output
    assert "  docs  " in output


def test_worker_alias_is_not_public_help(monkeypatch, capsys):
    _patch_signal(monkeypatch)

    assert cli.main(["__worker", "--help"]) == 2
    assert capsys.readouterr().err == (
        "error: unrecognized subcommand '__worker'\n\n"
        "Usage: varde [OPTIONS] <COMMAND>\n\n"
        "For more information, try '--help'.\n"
    )
