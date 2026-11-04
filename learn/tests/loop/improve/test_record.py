from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.loop.improve import record as rec
from varde_learn.loop.improve.record import LoopRecord, RecordError


def make(**over: object) -> LoopRecord:
    base = {
        "id": "trim-varde-x-1",
        "skill": "varde-x",
        "direction": "trim",
        "change": "move step a into a tool",
        "created": "2026-11-01",
        "trigger": ("f-1", "f-2"),
        "token_delta": -120,
        "later_demand": {"a": 2},
        "pre_hashes": {"skills/varde-x/SKILL.md": rec.hash_text("old")},
    }
    return LoopRecord(**{**base, **over})  # type: ignore[arg-type]


def test_round_trip(tmp_path: Path) -> None:
    record = make()
    rec.write_record(tmp_path, record, "--- a\n+++ b\n")
    assert rec.read_record(tmp_path, record.id) == record
    assert rec.read_diff(tmp_path, record) == "--- a\n+++ b\n"
    assert rec.list_records(tmp_path) == [record]
    assert (tmp_path / "loop" / "trim-varde-x-1.diff").is_file()
    assert (
        json.loads((tmp_path / "loop" / "trim-varde-x-1.json").read_text())["diff_path"]
        == "trim-varde-x-1.diff"
    )


@pytest.mark.parametrize("name", ["skill", "change", "id", "direction"])
def test_missing_field_rejected(name: str, tmp_path: Path) -> None:
    with pytest.raises(RecordError, match="missing field"):
        rec.to_json(make(**{name: ""}))
    data = json.loads(rec.to_json(make()))
    del data[name]
    with pytest.raises(RecordError, match="missing field"):
        rec.from_json(json.dumps(data))


def test_bad_state_direction_and_id_rejected() -> None:
    for over in ({"state": "done"}, {"direction": "up"}, {"id": "../x"}):
        with pytest.raises(RecordError):
            rec.validate(make(**over))


def test_unknown_field_rejected() -> None:
    data = json.loads(rec.to_json(make()))
    data["extra"] = 1
    with pytest.raises(RecordError, match="unknown field"):
        rec.from_json(json.dumps(data))


def test_list_empty_without_loop_dir(tmp_path: Path) -> None:
    assert rec.list_records(tmp_path) == []


def test_memory_list_and_surface_ignore_loop_dir(tmp_path, monkeypatch, capsys) -> None:
    from varde_learn.loop import cli_memory

    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    rec.write_record(tmp_path / "mem", make(), "--- a\n+++ b\n")
    for verb in ("list", "surface"):
        code = cli_memory.run(["memory", verb, "--json"])
        out = capsys.readouterr()
        assert code == 0, out.err
        assert "varde-x" not in out.out
        assert "loop" not in out.err
