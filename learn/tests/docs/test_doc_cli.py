"""CLI routing, usage errors, and committed help snapshots."""

from __future__ import annotations

import json
from types import SimpleNamespace

from varde_learn.docs.cli import help_text, run


def test_learn_entry_point_dispatches_docs_commands(tmp_path, capsys):
    from importlib.metadata import entry_points

    point = next(
        item for item in entry_points(group="varde.modules") if item.name == "learn"
    )
    module = point.load()()
    source = tmp_path / "SKILL.md"
    source.write_text('---\nname: sk\ndescription: "x."\n---\n# T\nShort.\n')
    assert module.run(["check", "--json", str(tmp_path)]) in {0, 1}
    assert '"outcome"' in capsys.readouterr().out
    assert module.run(["docs"]) == 2
    assert "Usage: varde learn docs <COMMAND>" in capsys.readouterr().err


def test_help_describes_flow_and_inventory_commands(capsys):
    module = SimpleNamespace(run=run, help=help_text)
    assert module.run(["flow", "--help"]) == 0
    assert (
        "Usage: varde learn measure <SKILL> flow [OPTIONS]" in capsys.readouterr().out
    )
    assert "Classify domain specifications" in module.help("docs spec")


def test_lint_json_and_input_error_route_to_existing_function(tmp_path, capsys):
    (tmp_path / "demo").mkdir()
    source = tmp_path / "demo" / "SKILL.md"
    source.write_text("---\nname: demo\ndescription: d\n---\n# A short skill\n")
    module = SimpleNamespace(run=run, help=help_text)
    assert module.run(["lint", "--json", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "success"

    assert module.run(["frontmatter", "--json", str(tmp_path / "missing")]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["data"]["error"]["code"] == "doc_frontmatter_input"


def test_json_usage_error_has_command_envelope(capsys):
    assert run(["lint", "--unknown", "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["outcome"] == "tool-error"
    assert error["data"]["error"]["code"] == "doc_lint_usage"
    assert "--unknown" in error["data"]["error"]["message"]


def test_repeated_json_option_is_a_clap_usage_error(capsys):
    assert run(["lint", "--json", "--json", "missing.md"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["data"]["error"]["code"] == "doc_lint_usage"
    assert "cannot be used multiple times" in error["data"]["error"]["message"]


def test_ledger_score_and_validate_do_not_require_git(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ledger = tmp_path / "ledger.json"
    ledger.write_text('{"decisions": [], "files": []}\n')
    assert run(["flow", "ledger", "score", str(ledger)]) == 0
    assert (
        capsys.readouterr().out
        == "cyclomatic 1 cognitive 0 decisions 0 branch_units 0\n"
    )
    assert run(["flow", "ledger", "validate", str(ledger)]) == 0
    assert capsys.readouterr().out == ""


def test_clap_option_errors_and_conflicts_are_usage_errors(tmp_path, capsys):
    module = SimpleNamespace(run=run, help=help_text)
    assert module.run(["lint", "--jso", "x"]) == 2
    assert "--jso" in capsys.readouterr().err
    assert module.run(["lint", "--json=true", "x"]) == 2
    assert "--json" in capsys.readouterr().err
    assert module.run(["flow", "--check", "--write", str(tmp_path)]) == 2
    conflict = capsys.readouterr().err
    assert "--check" in conflict and "--write" in conflict


def test_spec_without_subcommand_prints_help(capsys):
    assert run(["spec"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Usage: varde learn docs <COMMAND>" in captured.err
    assert "spec      Classify domain specifications" in captured.err


def test_repeated_value_option_is_a_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ledger = tmp_path / "ledger.json"
    ledger.write_text('{"decisions": [], "files": []}\n')
    assert (
        run(["flow", "ledger", "score", str(ledger), "--root", ".", "--root", "."]) == 2
    )
    error = capsys.readouterr().err
    assert "--root <DIR>" in error
    assert "cannot be used multiple times" in error


def test_invalid_ledger_action_reports_possible_values(capsys):
    assert run(["flow", "ledger", "bad", "ledger.json"]) == 2
    error = capsys.readouterr().err
    assert "invalid value 'bad' for '<ACTION>'" in error
    assert "[possible values: hash, validate, score, check]" in error


def test_unknown_subcommand_includes_help_hint(capsys):
    assert run(["bogus"]) == 2
    assert capsys.readouterr().err == (
        "error: unrecognized subcommand 'bogus'\n\n"
        "Usage: varde learn docs <COMMAND>\n\nFor more information, try '--help'.\n"
    )


def test_flow_json_routes_to_analysis(tmp_path, capsys):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# A short skill\n")

    assert run(["flow", "--json", str(skill)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "success"
    assert payload["data"][0]["skill"] == skill.name


def test_cli_json_is_compact_and_sorted(tmp_path, capsys):
    source = tmp_path / "clean.md"
    source.write_text("# Clean\n")
    assert run(["lint", "--json", str(source)]) == 0
    assert capsys.readouterr().out.startswith('{"data":')


def test_option_equals_and_option_terminator(tmp_path, capsys):
    ledger = tmp_path / "ledger.json"
    ledger.write_text('{"decisions": [], "files": []}\n')
    assert run(["flow", "ledger", "score", str(ledger), "--root=."]) == 0
    assert (
        capsys.readouterr().out
        == "cyclomatic 1 cognitive 0 decisions 0 branch_units 0\n"
    )

    source = tmp_path / "--json"
    source.write_text("# Clean\n")
    assert run(["lint", "--", str(source)]) == 0
    assert capsys.readouterr().out.endswith(
        "0 error(s), 0 warning(s) across 1 file(s).\n"
    )


def test_doc_without_subcommand_exits_two_to_stderr(capsys):
    assert run([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Serve, comment on and recap Markdown documents")
