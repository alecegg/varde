import json
from pathlib import Path

import pytest
from varde_learn.knowledge.cmdbase import (
    CliError,
    Fix,
    InternalError,
    page_bounds,
    pagination_meta,
    print_error,
    print_failure,
    print_success,
    read_input,
    report_error,
)


def test_success_and_failure_render_envelopes(capsys):
    print_success({"ok": "✓"})
    assert json.loads(capsys.readouterr().out)["data"] == {"ok": "✓"}

    print_failure(
        "invalid_input", "bad", {"field": "slug", "fix": {"reason": "repair"}}
    )
    error = json.loads(capsys.readouterr().out)["data"]["error"]
    assert error["details"] == {"field": "slug"}
    assert error["fix"] == {"reason": "repair"}


def test_error_reporting_returns_exit_code_and_routes_json(capsys):
    assert report_error(CliError("bad flag"), json=True) == 1
    assert (
        json.loads(capsys.readouterr().err)["data"]["error"]["code"] == "invalid_input"
    )

    report_error(InternalError("broken"), json=True)
    assert "fix" in json.loads(capsys.readouterr().err)["data"]["error"]


def test_output_error_and_pagination(capsys):
    print_error("internal", "broken")
    assert json.loads(capsys.readouterr().err)["outcome"] == "tool-error"
    assert page_bounds(8, 7, 4, False) == (7, 8)
    assert page_bounds(8, 10, 4, False) == (8, 8)
    assert pagination_meta(8, 2, 5, 3, False)["pagination"]["next_offset"] == 5
    assert Fix.no_command("why").as_value() == {"reason": "why"}


def test_read_input_file_empty_and_stdin(monkeypatch, tmp_path: Path):
    file = tmp_path / "input.md"
    file.write_bytes(b"body")
    assert read_input(file) == b"body"
    file.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        read_input(file)

    class Stdin:
        buffer = type("Buffer", (), {"read": staticmethod(lambda: b"stdin")})()

    monkeypatch.setattr("varde_learn.knowledge.cmdbase.input.sys.stdin", Stdin())
    assert read_input() == b"stdin"
