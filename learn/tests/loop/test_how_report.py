from __future__ import annotations

import io
import json
from dataclasses import dataclass, field

import pytest
from varde_learn.loop import cli_how_report
from varde_learn.loop.calls import FAILURE, SUCCESS

_NOW = "2026-10-22T10:00:00+00:00"


class _Io:
    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


_LEDGER: list = []


@pytest.fixture(autouse=True)
def _ledger(monkeypatch):
    _LEDGER.clear()
    monkeypatch.setattr(
        cli_how_report.analyzed, "read_all", lambda store: list(_LEDGER)
    )
    monkeypatch.setattr(cli_how_report, "resolve_store_dir", lambda: None)


def _row(session, skills=None, at=_NOW, harness="claude"):
    row = {"session": session, "harness": harness, "analyzed_at": at}
    if skills is not None:
        row["metrics"] = {"skills": skills}
    return row


def _skill(loads=(), skip=False, errors=0, first=None):
    return {
        "loads": list(loads),
        "post_errors": errors,
        "first_error": first,
        "suspected_skip": skip,
    }


@dataclass
class _Item:
    target: str | None
    tags: list[str] = field(default_factory=list)
    created_at: str = _NOW
    source: str = ""
    id: str = "fr-1"


class _Repo:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def list_items(self, *, offset=0, limit=100):
        self.calls.append((offset, limit))
        chunk = self.items[offset : offset + limit]
        return type("Page", (), {"items": tuple(chunk), "total": len(self.items)})()


def _call(
    arg: str | None,
    status: str = SUCCESS,
    session: str | None = "s1",
    command: str = "doc how",
):
    row = {
        "ts": _NOW,
        "command": command,
        "status": status,
        "duration_s": 0.1,
        "session": session,
    }
    if arg is not None:
        row["arg"] = arg
    return row


def _run(monkeypatch, calls, items, tmp_path, lines=None, extra=()):
    monkeypatch.setattr(cli_how_report, "read_calls_strict", lambda: calls)
    monkeypatch.setattr(cli_how_report, "open_repository", lambda: _Repo(items))
    argv = ["skills", "demand", "--json", *extra]
    if lines is not None:
        path = tmp_path / "changelog.jsonl"
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
        argv += ["--changelog", str(path)]
    output = _Io()
    code = cli_how_report.run(argv, output)
    return code, output


def _steps(output):
    data = json.loads(output.stdout.getvalue())["data"]
    return {row["step"]: row for row in data["steps"]}, data


def test_requests_sessions_and_failures(monkeypatch, tmp_path):
    calls = [
        _call("varde-docs/a", session="s1"),
        _call("varde-docs/a", session="s1"),
        _call("varde-docs/a", session=None),
        _call("varde-docs/a", session="s2", status=FAILURE),
        _call("varde-docs/b", session="s2"),
        _call(None, session="s3"),
        _call("varde-docs/a", session="s9", command="doc lint"),
    ]
    code, output = _run(monkeypatch, calls, [], tmp_path)
    steps, data = _steps(output)
    assert code == 0
    assert steps["varde-docs/a"] | {} == {
        "step": "varde-docs/a",
        "requests": 3,
        "failures": 1,
        "unknown_session_requests": 1,
        "sessions": 1,
        "friction": 0,
        "friction_ids": [],
        "fills": 0,
    }
    assert steps["varde-docs/b"]["sessions"] == 1
    existing = {
        "skill": "varde-docs",
        "sessions_with_request": 2,
        "unknown_session_requests": 1,
        "friction_items": 0,
    }
    [row] = data["skills"]
    new_keys = {
        "runs",
        "runs_with_load",
        "suspected_skips",
        "suspected_skip_candidates",
        "how_skip_friction",
    }
    assert set(row) == set(existing) | new_keys
    assert existing.items() <= row.items()
    assert row["runs"] == 0
    assert row["suspected_skips"] == 0


def test_friction_target_wins_over_tag_and_pages(monkeypatch, tmp_path):
    lines = [
        {"id": "st-g1-001", "kind": "cut", "step": "varde-docs/a"},
        {"id": "st-g1-002", "kind": "cut", "step": "varde-docs/b"},
    ]
    items = [
        _Item("how/varde-docs/a", ["st-g1-002"]),  # target wins: step a
        _Item(None, ["st-g1-002"]),  # tag only: step b
        _Item("skills/x#sec", ["st-g1-001"]),  # non-how target: tag decides
        _Item("how/varde-docs/c"),
        _Item(None, ["other"]),
    ]
    _, output = _run(monkeypatch, [], items, tmp_path, lines)
    steps, _ = _steps(output)
    assert steps["varde-docs/a"]["friction"] == 2
    assert steps["varde-docs/b"]["friction"] == 1
    assert steps["varde-docs/c"]["friction"] == 1


def test_friction_pages_until_exhausted():
    repo = _Repo([_Item("how/s/a") for _ in range(2_500)])
    assert len(cli_how_report._read_friction(repo)) == 2_500
    assert repo.calls == [(0, 1000), (1000, 1000), (2000, 1000)]


def test_fills_count_active_only_and_use_cut_step(monkeypatch, tmp_path):
    lines = [
        {"id": "st-g1-001", "kind": "cut", "step": "varde-docs/a"},
        {
            "id": "fill-g1-001",
            "kind": "fill",
            "cut_id": "st-g1-001",
            "status": "active",
        },
        {
            "id": "fill-g1-002",
            "kind": "fill",
            "cut_id": "st-g1-001",
            "status": "dropped",
        },
        {
            "id": "fill-g1-003",
            "kind": "fill",
            "step": "varde-docs/b",
            "status": "active",
        },
    ]
    _, output = _run(monkeypatch, [], [], tmp_path, lines)
    steps, _ = _steps(output)
    assert steps["varde-docs/a"]["fills"] == 1
    assert steps["varde-docs/b"]["fills"] == 1


def test_window_excludes_old_rows(monkeypatch, tmp_path):
    old = _call("varde-docs/a") | {"ts": "2020-01-01T00:00:00+00:00"}
    _, output = _run(monkeypatch, [old], [], tmp_path, extra=("--window", "30d"))
    steps, _ = _steps(output)
    assert steps == {}


def test_text_output_and_help(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_how_report, "read_calls_strict", lambda: [_call("s/a")])
    monkeypatch.setattr(cli_how_report, "open_repository", lambda: _Repo([]))
    output = _Io()
    assert cli_how_report.run(["skills", "demand"], output) == 0
    assert "s/a: 1 requests (0 failed), 1 sessions" in output.stdout.getvalue()
    helped = _Io()
    assert cli_how_report.run(["skills", "demand", "--help"], helped) == 0
    assert "Usage: varde learn skills demand" in helped.stdout.getvalue()


def test_bad_arguments_exit_2():
    output = _Io()
    assert cli_how_report.run(["skills", "demand", "--window"], output) == 2
    assert "requires a value" in output.stderr.getvalue()
    assert cli_how_report.run(["skills", "demand", "--bogus"], _Io()) == 2


def test_learn_module_dispatches_and_does_not_import_doc():
    from varde_learn.module import register

    assert "skills" in register().help()


def _skills(output):
    _, data = _steps(output)
    return {row["skill"]: row for row in data["skills"]}, data


def test_ledger_rows_runs_loads_and_skips(monkeypatch, tmp_path):
    _LEDGER.extend(
        [
            _row("a", {"varde-plan": _skill(["x"])}),
            _row("b", {"varde-plan": _skill(skip=True, errors=2, first="boom")}),
            _row("c"),
            _row("d", {}),
        ]
    )
    _, output = _run(monkeypatch, [], [], tmp_path)
    skills, data = _skills(output)
    plan = skills["varde-plan"]
    assert (plan["runs"], plan["runs_with_load"], plan["suspected_skips"]) == (2, 1, 1)
    assert plan["suspected_skip_candidates"] == [
        {"session": "b", "harness": "claude", "post_errors": 2, "first_error": "boom"}
    ]
    assert data["swept_sessions"] == 4
    assert plan["sessions_with_request"] == 0


def test_no_load_skill_reports_null(monkeypatch, tmp_path):
    _LEDGER.append(_row("a", {"varde-x": _skill(skip=True, errors=1)}))
    _, output = _run(monkeypatch, [], [], tmp_path)
    skills, _ = _skills(output)
    assert skills["varde-x"]["runs"] == 1
    assert skills["varde-x"]["suspected_skips"] is None


def test_ledger_and_calls_disagree(monkeypatch, tmp_path):
    _LEDGER.append(_row("a", {"varde-docs": _skill(skip=True, errors=1)}))
    calls = [_call("varde-docs/a", session="s9"), _call("varde-docs/b", session="s8")]
    _, output = _run(monkeypatch, calls, [], tmp_path)
    skill = _skills(output)[0]["varde-docs"]
    assert skill["sessions_with_request"] == 2
    assert skill["runs"] == 1
    assert skill["runs_with_load"] == 0
    assert skill["suspected_skips"] == 1


def test_skill_known_only_from_friction_or_ledger(monkeypatch, tmp_path):
    items = [_Item(None, source="varde-f", tags=["skilltrim", "how-skip"])]
    items.append(_Item(None, source="varde-f", tags=["other"]))
    _LEDGER.append(_row("a", {"varde-l": _skill()}))
    _, output = _run(monkeypatch, [], items, tmp_path)
    skills, _ = _skills(output)
    assert skills["varde-f"]["how_skip_friction"] == 1
    assert skills["varde-f"]["runs"] == 0
    assert skills["varde-f"]["suspected_skips"] is None
    assert skills["varde-l"]["how_skip_friction"] == 0


def test_ledger_window_uses_analyzed_at(monkeypatch, tmp_path):
    _LEDGER.extend(
        [
            _row("old", {"varde-p": _skill(["x"])}, at="2020-01-01T00:00:00+00:00"),
            _row("new", {"varde-p": _skill(["x"])}),
        ]
    )
    extra = ("--window", "30d")
    _, output = _run(monkeypatch, [], [], tmp_path, extra=extra)
    skills, data = _skills(output)
    assert data["swept_sessions"] == 1
    assert skills["varde-p"]["runs"] == 1


def test_candidates_capped(monkeypatch, tmp_path):
    _LEDGER.append(_row("ok", {"varde-p": _skill(["x"])}))
    _LEDGER.extend(
        _row(f"s{n}", {"varde-p": _skill(skip=True, errors=1)}) for n in range(25)
    )
    _, output = _run(monkeypatch, [], [], tmp_path)
    plan = _skills(output)[0]["varde-p"]
    assert plan["suspected_skips"] == 25
    assert len(plan["suspected_skip_candidates"]) == 20


def test_text_shows_skill_columns_and_help_terms(monkeypatch, tmp_path):
    _LEDGER.append(_row("a", {"varde-p": _skill(["x"])}))
    monkeypatch.setattr(cli_how_report, "read_calls_strict", list)
    monkeypatch.setattr(cli_how_report, "open_repository", lambda: _Repo([]))
    output = _Io()
    cli_how_report.run(["skills", "demand"], output)
    text = output.stdout.getvalue()
    assert "Swept sessions: 1" not in text  # no steps: short message only
    helped = _Io()
    cli_how_report.run(["skills", "demand", "--help"], helped)
    for term in ("swept_sessions", "candidates", "precision limit", "--tag how-skip"):
        assert term in helped.stdout.getvalue().replace("--tag skilltrim ", "")


def test_text_with_steps_lists_runs(monkeypatch, tmp_path):
    _LEDGER.append(_row("a", {"varde-p": _skill(["x"])}))
    monkeypatch.setattr(
        cli_how_report, "read_calls_strict", lambda: [_call("varde-p/x")]
    )
    monkeypatch.setattr(cli_how_report, "open_repository", lambda: _Repo([]))
    output = _Io()
    cli_how_report.run(["skills", "demand"], output)
    text = output.stdout.getvalue()
    assert "Swept sessions: 1" in text
    assert "1 runs, 1 with load, 0 suspected skips, 0 how-skip friction" in text


def test_demand_counts_doc_how_and_learn_how_rows(monkeypatch, tmp_path):
    calls = [
        _call("s/a", session="s1", command="doc how"),
        _call("s/a", session="s2", command="learn how"),
    ]
    code, output = _run(monkeypatch, calls, [], tmp_path)
    assert code == 0
    rows, _ = _steps(output)
    assert rows["s/a"]["requests"] == 2
    assert rows["s/a"]["sessions"] == 2


def test_demand_without_argument_lists_all_skills(monkeypatch, tmp_path):
    calls = [_call("s/a"), _call("t/b", command="learn how")]
    code, output = _run(monkeypatch, calls, [], tmp_path)
    assert code == 0
    skills, _ = _skills(output)
    assert set(skills) == {"s", "t"}


def test_demand_with_skill_shows_only_its_steps(monkeypatch, tmp_path):
    calls = [_call("s/a"), _call("s/b", command="learn how"), _call("t/c")]
    code, output = _run(monkeypatch, calls, [], tmp_path, extra=("s",))
    assert code == 0
    rows, data = _steps(output)
    assert set(rows) == {"s/a", "s/b"}
    assert [row["skill"] for row in data["skills"]] == ["s"]


def test_tool_rows_count_as_requests_for_their_step(monkeypatch, tmp_path):
    calls = [
        _call("varde-x/step", command="tool varde-x"),
        _call("varde-x/step", command="tool varde-x", status=FAILURE),
        _call("varde-x/other", command="tool varde-x", session=None),
        _call("varde-x/step", command="learn how"),
    ]
    code, output = _run(monkeypatch, calls, [], tmp_path)
    steps, _ = _steps(output)
    assert code == 0
    assert steps["varde-x/step"]["requests"] == 2
    assert steps["varde-x/step"]["failures"] == 1
    assert steps["varde-x/other"]["unknown_session_requests"] == 1
    assert set(steps["varde-x/step"]) == {
        "step",
        "requests",
        "failures",
        "unknown_session_requests",
        "sessions",
        "friction",
        "friction_ids",
        "fills",
    }
