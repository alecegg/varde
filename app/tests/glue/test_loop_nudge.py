from __future__ import annotations

from pathlib import Path

import pytest
from varde.glue import hook, loop_nudge
from varde_learn.loop.improve import record as rec


@pytest.fixture
def memory_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "mem"
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(root))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.toml").write_text(
        '[instructions]\ntargets = ["x.md"]\n'
        '[hooks.session_start]\nproviders = ["loop_nudge"]\n'
    )
    return root


def write(root: Path, record_id: str, skill: str, state: str = "proposed") -> None:
    record = rec.LoopRecord(
        id=record_id,
        skill=skill,
        direction="trim",
        change="c",
        created="2026-11-01T00:00:00Z",
        state=state,
    )
    rec.write_record(root, record, "")


def test_line_is_empty_for_zero_and_names_the_command() -> None:
    assert loop_nudge.nudge_line(0) == ""
    assert loop_nudge.nudge_line(3) == (
        "3 skills have proposals ready; run `varde learn skills candidates`"
    )
    assert loop_nudge.nudge_line(1).startswith("1 skill has proposals ready")


def test_only_proposed_records_count_once_per_skill() -> None:
    def record(skill: str, state: str) -> rec.LoopRecord:
        return rec.LoopRecord("i", skill, "add", "c", "t", state=state)

    records = [
        record("a", "proposed"),
        record("a", "proposed"),
        record("b", "applied"),
        record("c", "rejected"),
    ]
    assert loop_nudge.skills_with_open_proposals(records) == 1


def test_session_start_adds_one_line_for_open_proposals(memory_root, capsys) -> None:
    write(memory_root, "p1", "varde-x")
    write(memory_root, "p2", "varde-y")
    write(memory_root, "p3", "varde-z", state="rejected")
    hook.session_start("pi", b'{"session_id":"s"}')
    out = capsys.readouterr().out
    assert out.count("proposals ready") == 1
    assert "2 skills have proposals ready; run `varde learn skills candidates`" in out


def test_session_start_adds_nothing_without_proposals(memory_root, capsys) -> None:
    hook.session_start("pi", b'{"session_id":"s"}')
    assert "proposals ready" not in capsys.readouterr().out


def test_failing_provider_yields_a_notice(memory_root, monkeypatch, capsys) -> None:
    def boom(_cwd):
        raise OSError("boom")

    monkeypatch.setattr(loop_nudge, "loop_nudge_section", boom)
    hook.session_start("pi", b'{"session_id":"s"}')
    assert "provider `loop_nudge` skipped: failed" in capsys.readouterr().out


def test_default_providers_include_loop_nudge() -> None:
    providers, _, _ = hook._session_providers(
        {"instructions": {"targets": ["x"]}}, None
    )
    assert "loop_nudge" in providers


def test_a_malformed_record_is_ignored_without_a_notice(memory_root, capsys) -> None:
    write(memory_root, "p1", "varde-x")
    (rec.loop_dir(memory_root) / "broken.json").write_text("{not json")
    hook.session_start("pi", b'{"session_id":"s"}')
    out = capsys.readouterr().out
    assert "1 skill has proposals ready" in out
    assert "skipped" not in out
