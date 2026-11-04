from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.loop import calls, cli_how_report
from varde_learn.loop.improve import tool_entry as te


def make_module(root: Path, skill: str, step: str, body: str = "") -> Path:
    """A fixture module root with one registered tool (any module, not learn)."""
    script = root / te.TOOLS_DIR / te.entry_for(skill, step)
    script.parent.mkdir(parents=True)
    script.write_text(body or "def run(args):\n    print('ran', args)\n    return 0\n")
    row = te.ToolRow(skill, step, te.entry_for(skill, step))
    te.registry_path(root).write_text(te.add_row("", row))
    return root


def test_registry_round_trip_and_duplicate_rejected() -> None:
    first = te.ToolRow("varde-x", "a", "varde-x/a.py")
    text = te.add_row("", first)
    text = te.add_row(text, te.ToolRow("varde-x", "b", "varde-x/b.py"))
    assert [r.step for r in te.parse_registry(text)] == ["a", "b"]
    with pytest.raises(te.ToolError, match="already registered"):
        te.add_row(text, first)


def test_invalid_rows_rejected() -> None:
    with pytest.raises(te.ToolError):
        te.validate_row(te.ToolRow("Bad Skill", "a", "x"))
    with pytest.raises(te.ToolError):
        te.validate_row(te.ToolRow("varde-x", "a", "other.py"))
    with pytest.raises(te.ToolError):
        te.parse_registry('[[tool]]\nskill = "varde-x"\n')


def test_non_learn_module_root_is_a_parameter(tmp_path: Path) -> None:
    root = make_module(tmp_path / "dev_pkg", "varde-pr", "facts")
    assert [r.step for r in te.load_registry(root)] == ["facts"]
    assert te.load_registry(tmp_path / "missing") == []
    found = te.find_tool([tmp_path / "missing", root], "varde-pr", "facts")
    assert found is not None and found[0] == root


def test_counted_call_appends_expected_call_row(tmp_path, monkeypatch, capsys) -> None:
    root = make_module(tmp_path / "pkg", "varde-x", "step")
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: store)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "sess-1")
    code = te.run_counted("varde-x", "step", ["a"], [root])
    assert code == 0
    assert "ran ['a']" in capsys.readouterr().out
    [row] = calls.read_calls_strict(store)
    assert row["command"] == "tool varde-x"
    assert row.get("arg") == "varde-x/step"
    assert row["status"] == calls.SUCCESS
    assert row["session"] == "sess-1"
    assert row["duration_s"] >= 0
    assert calls.parse_timestamp(row["ts"]) is not None


def test_failing_tool_is_counted_as_failure(tmp_path, monkeypatch) -> None:
    root = make_module(
        tmp_path / "pkg", "varde-x", "step", "def run(args):\n    return 3\n"
    )
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    assert te.run_counted("varde-x", "step", [], [root]) == 3
    assert calls.read_calls_strict(tmp_path)[0]["status"] == calls.FAILURE


def test_unregistered_tool_exits_2_and_counts_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    assert te.run_counted("varde-x", "none", [], [tmp_path]) == 2
    assert calls.read_calls_strict(tmp_path) == []


def test_skills_demand_counts_the_tool_row(tmp_path) -> None:
    row = calls.tool_call_row(
        "varde-x", "step", status=calls.SUCCESS, duration_s=0.1, session="s"
    )
    report = cli_how_report.build_report([row], [], [])
    assert report["steps"][0]["step"] == "varde-x/step"
    assert report["steps"][0]["requests"] == 1
