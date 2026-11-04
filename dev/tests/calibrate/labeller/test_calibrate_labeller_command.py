import json
from pathlib import Path

from varde_dev.calibrate.labeller.commands import main
from varde_dev.calibrate.store import import_dataset, init_dataset


def _dataset(path: Path, *, count: int = 2) -> Path:
    init_dataset(path)
    items = []
    units = []
    tasks = []
    for index in range(count):
        task_id = f"task-{index}"
        unit_id = f"unit-{index}"
        tasks.append({"id": task_id, "description": f"Sort values for {index}"})
        ids = [f"item-{index}-a", f"item-{index}-b"]
        items.extend(
            [
                {
                    "id": ids[0],
                    "language": "python",
                    "task_id": task_id,
                    "pair_group_id": task_id,
                    "text": f"return {index}",
                    "license": "MIT",
                    "split": "dev",
                    "metadata": {"category": "SECRET", "variant": "SECRET"},
                },
                {
                    "id": ids[1],
                    "language": "python",
                    "task_id": task_id,
                    "pair_group_id": task_id,
                    "text": f"return {index} + 1",
                    "license": "MIT",
                    "split": "dev",
                    "metadata": {"file_name": "SECRET.py", "score": 876},
                },
            ]
        )
        units.append(
            {
                "id": unit_id,
                "kind": "pair",
                "item_ids": ids,
                "pair_group_id": task_id,
                "task_id": task_id,
                "split": "dev",
            }
        )
    import_dataset(path, items=items, units=units, tasks=tasks)
    return path


def _records(path: Path, filename: str) -> list[dict[str, object]]:
    lines = (path / filename).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[1:] if line]


def _feed(monkeypatch, answers):
    values = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(values))


def test_pause_resume_and_skip_save_cursor_without_duplicate_labels(
    tmp_path, monkeypatch, capsys
):
    dataset = _dataset(tmp_path / "dataset")
    _feed(monkeypatch, ["s", "p"])
    assert main([str(dataset), "--session", "resume-test", "--seed", "8"]) == 0
    output = capsys.readouterr().out
    assert (
        f"python -m varde_dev.calibrate label {dataset} --session resume-test" in output
    )
    session_path = dataset / "sessions" / "resume-test.json"
    paused = json.loads(session_path.read_text())
    assert paused["cursor"] == 1
    assert paused["skipped"]
    _feed(monkeypatch, ["a", "h", "clear", "b", "h", "clear"])
    assert main([str(dataset), "--session", "resume-test"]) == 0
    labels = _records(dataset, "labels/batch-000001.jsonl") + _records(
        dataset, "labels/batch-000002.jsonl"
    )
    assert len(labels) == 2
    assert {label["choice"] for label in labels} == {"A", "B"}
    assert all(label["duration_ms"] >= 0 for label in labels)
    saved = json.loads(session_path.read_text())
    assert saved["cursor"] == len(saved["schedule"])
    assert len(saved["skipped_history"]) == 1


def test_eof_after_choice_pauses_without_partial_label(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path / "dataset", count=1)
    answers = iter(["a"])

    def input_after_choice(_prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", input_after_choice)
    assert main([str(dataset), "--session", "cut-input", "--seed", "4"]) == 0
    saved = json.loads((dataset / "sessions" / "cut-input.json").read_text())
    assert saved["cursor"] == 0
    assert saved["paused"] is True
    assert saved["records"] == []
    manifest = (dataset / "manifest.toml").read_text()
    assert 'id = "batch-000001"' not in manifest


def test_reason_on_any_unit_and_amend_append_reference(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path / "dataset", count=2)
    _feed(
        monkeypatch,
        ["a", "h", "r", "because", "amend", "1", "b", "m", "r", "revised", "p"],
    )
    assert main([str(dataset), "--session", "amend-test", "--seed", "4"]) == 0
    first = _records(dataset, "labels/batch-000001.jsonl")[0]
    second = _records(dataset, "labels/batch-000002.jsonl")[0]
    assert first["reason"] == "because"
    assert second["amends"] == first["record_id"]
    assert second["choice"] == "B"
    assert second["reason"] == "revised"
    assert second["duration_ms"] >= 0


def test_terminal_display_does_not_expose_item_metadata(tmp_path, monkeypatch, capsys):
    dataset = _dataset(tmp_path / "dataset", count=1)
    _feed(monkeypatch, ["p"])
    assert main([str(dataset), "--session", "blind-test", "--seed", "4"]) == 0
    output = capsys.readouterr().out
    for forbidden in ("SECRET", "SECRET.py", "876", "category", "variant", "score"):
        assert forbidden not in output


def test_cli_places_configured_roles_and_repeats(tmp_path, monkeypatch, capsys):
    dataset = _dataset(tmp_path / "dataset", count=6)
    (dataset / "label-config.json").write_text(
        json.dumps({"controls": ["unit-4"], "distractors": ["unit-5"]}),
        encoding="utf-8",
    )
    _feed(monkeypatch, ["p"])
    assert (
        main(
            [
                str(dataset),
                "--session",
                "role-test",
                "--seed",
                "17",
                "--control-every",
                "2",
                "--control-positions",
                "1=unit-4",
                "--reshow-interval",
                "2",
                "--distractors",
                "1",
                "--reason-rate",
                "0.5",
                "--break-every",
                "2",
                "--max-minutes",
                "60",
            ]
        )
        == 0
    )
    saved = json.loads((dataset / "sessions" / "role-test.json").read_text())
    schedule = saved["schedule"]
    assert schedule[0]["role"] == "control"
    assert schedule[1]["role"] == "control"
    assert sum(entry["role"] == "control" for entry in schedule) >= 1
    assert sum(entry["role"] == "distractor" for entry in schedule) == 1
    assert any(entry["reason_prompt"] for entry in schedule)
    assert any(entry["break_after"] for entry in schedule)
    assert all(
        entry["unit_id"] not in {"unit-4", "unit-5"}
        for entry in schedule
        if entry["role"] == "standard"
    )
    reshow_indexes = [
        i for i, entry in enumerate(schedule) if entry["role"] == "reshow"
    ]
    assert reshow_indexes
    for index in reshow_indexes:
        repeated_id = schedule[index]["unit_id"]
        original_index = next(
            i
            for i, entry in enumerate(schedule[:index])
            if entry["unit_id"] == repeated_id and entry["role"] == "standard"
        )
        assert index - original_index >= 3
    assert all("role:" not in line for line in capsys.readouterr().out.splitlines())


def test_triple_saves_three_pair_labels_through_store_api(tmp_path, monkeypatch):
    from varde_dev.calibrate.store import import_dataset, init_dataset, verify_dataset

    dataset = init_dataset(tmp_path / "triple-dataset")
    task = {"id": "task", "description": "Compare three implementations"}
    items = [
        {
            "id": f"item-{index}",
            "language": "python",
            "task_id": "task",
            "pair_group_id": "group",
            "text": f"return {index}",
            "license": "MIT",
            "split": "dev",
        }
        for index in range(3)
    ]
    unit = {
        "id": "triple",
        "kind": "triple",
        "item_ids": [item["id"] for item in items],
        "pair_group_id": "group",
        "task_id": "task",
        "split": "dev",
    }
    import_dataset(dataset, items=items, units=[unit], tasks=[task])
    _feed(monkeypatch, ["a", "h", "", "b", "m", "", "t", "l", ""])
    assert main([str(dataset), "--session", "triple-test", "--seed", "3"]) == 0
    labels = _records(dataset, "labels/batch-000001.jsonl")
    assert len(labels) == 3
    assert all("::pair-" in label["unit_id"] for label in labels)
    assert verify_dataset(dataset) == []


def test_single_unit_is_skipped_and_session_completes(tmp_path, monkeypatch, capsys):
    from varde_dev.calibrate.store import import_dataset, init_dataset

    dataset = init_dataset(tmp_path / "single-dataset")
    item = {
        "id": "anchor",
        "language": "python",
        "task_id": "anchor-task",
        "pair_group_id": "anchor-group",
        "text": "return 1",
        "license": "MIT",
        "split": "dev",
    }
    import_dataset(
        dataset,
        items=[item],
        units=[
            {
                "id": "single",
                "kind": "single",
                "item_ids": ["anchor"],
                "pair_group_id": "anchor-group",
                "task_id": "anchor-task",
                "split": "dev",
            }
        ],
        tasks=[{"id": "anchor-task", "description": "Rate an anchor"}],
    )
    _feed(monkeypatch, [])
    assert main([str(dataset), "--session", "single-test"]) == 0
    assert "ordinal rating is not available" in capsys.readouterr().out
    session = json.loads((dataset / "sessions" / "single-test.json").read_text())
    assert session["cursor"] == len(session["schedule"])
    assert "[[label_batches]]" not in (dataset / "manifest.toml").read_text()


def test_completed_session_rerun_does_not_rewrite_completion_time(
    tmp_path, monkeypatch, capsys
):
    dataset = _dataset(tmp_path / "dataset", count=1)
    _feed(monkeypatch, ["a", "h", ""])
    assert main([str(dataset), "--session", "complete-test", "--seed", "4"]) == 0
    path = dataset / "sessions" / "complete-test.json"
    before = path.read_bytes()
    completed_at = json.loads(before)["completed_at"]
    assert main([str(dataset), "--session", "complete-test"]) == 0
    assert "already complete" in capsys.readouterr().out
    assert path.read_bytes() == before
    assert json.loads(path.read_bytes())["completed_at"] == completed_at


def test_paused_wall_time_does_not_trigger_hard_stop(tmp_path, monkeypatch, capsys):
    dataset = _dataset(tmp_path / "dataset", count=1)
    _feed(monkeypatch, ["p"])
    assert main([str(dataset), "--session", "timer-test", "--seed", "4"]) == 0
    path = dataset / "sessions" / "timer-test.json"
    session = json.loads(path.read_text())
    session["started_at"] = "2000-01-01T00:00:00+00:00"
    session["active_seconds"] = 1
    path.write_text(json.dumps(session), encoding="utf-8")
    _feed(monkeypatch, ["a", "h", ""])
    assert main([str(dataset), "--session", "timer-test", "--max-minutes", "2"]) == 0
    assert "Hard-stop time reached" not in capsys.readouterr().out
