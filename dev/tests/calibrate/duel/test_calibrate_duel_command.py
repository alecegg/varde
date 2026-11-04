import json
import subprocess
import sys
import tomllib
from itertools import pairwise
from pathlib import Path

from varde_dev.calibrate.duel.commands import main
from varde_dev.calibrate.store import import_dataset, init_dataset, verify_dataset


def _dataset(
    path: Path,
    *,
    groups=("zz-group-secret", "zz-group-secret", "zz-group-secret", "zz-group-secret"),
) -> Path:
    init_dataset(path)
    items = []
    units = []
    tasks = []
    for group in dict.fromkeys(groups):
        task_id = f"task-{group}"
        tasks.append({"id": task_id, "description": "Compare implementations"})
        ids = []
        for index, actual_group in enumerate(groups):
            if actual_group != group:
                continue
            item_id = f"item-{group}-{index}"
            ids.append(item_id)
            items.append(
                {
                    "id": item_id,
                    "language": "python",
                    "task_id": task_id,
                    "pair_group_id": group,
                    "text": f"code {index}",
                    "license": "MIT",
                    "split": "dev",
                    "metadata": {
                        "score": 99,
                        "category": "secret",
                        "variant": "secret",
                        "file_name": "secret.py",
                    },
                }
            )
        for left, right in pairwise(ids):
            units.append(
                {
                    "id": f"unit-{left}-{right}",
                    "kind": "pair",
                    "item_ids": [left, right],
                    "pair_group_id": group,
                    "task_id": task_id,
                    "split": "dev",
                }
            )
    import_dataset(path, items=items, units=units, tasks=tasks)
    return path


def test_adaptive_duel_stops_confident_and_writes_verified_blind_labels(
    tmp_path, monkeypatch, capsys
):
    dataset = _dataset(tmp_path / "data")
    seen = []
    prompt_count = 0

    def consistent_answer(_prompt=""):
        nonlocal prompt_count
        prompt_count += 1
        if prompt_count % 2 == 0:
            return ""
        output = capsys.readouterr().out
        seen.append(output)
        pair = output.rsplit("A:\n", 1)[1].split("\n\nB:\n", 1)
        return "a" if int(pair[0].split()[-1]) > int(pair[1].split()[-1]) else "b"

    monkeypatch.setattr("builtins.input", consistent_answer)
    assert (
        main(
            [
                str(dataset),
                "--session",
                "same",
                "--group",
                "zz-group-secret",
                "--seed",
                "4",
            ]
        )
        == 0
    )
    output = "\n".join(seen) + capsys.readouterr().out
    assert "confidence" in output.lower()
    assert "uncertainty by group" in output.lower()
    assert "confident" in output.lower()
    assert "99" not in output and "secret" not in output and "secret.py" not in output
    labels = []
    for batch in tomllib.loads((dataset / "manifest.toml").read_text())[
        "label_batches"
    ]:
        lines = (
            (dataset / "labels" / f"{batch['id']}.jsonl").read_text().splitlines()[1:]
        )
        labels.extend(json.loads(line) for line in lines)
    assert 0 < len(labels) < 6
    assert all(
        label["label_source"] == "duel" and label["rater_kind"] == "human"
        for label in labels
    )
    assert verify_dataset(dataset) == []


def test_pause_eof_resume_no_partial_or_duplicate_labels(tmp_path, monkeypatch, capsys):
    dataset = _dataset(tmp_path / "data")
    answers = iter(["a", "why", "p"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert (
        main(
            [
                str(dataset),
                "--session",
                "resume",
                "--group",
                "zz-group-secret",
                "--seed",
                "4",
            ]
        )
        == 0
    )
    saved = json.loads((dataset / "sessions" / "duel-resume.json").read_text())
    assert saved["cursor"] == 1
    assert len(saved["labels"]) == 1
    labels_before = sum(
        1
        for path in (dataset / "labels").glob("*.jsonl")
        for line in path.read_text().splitlines()[1:]
        if line
    )
    answers = iter(["b", "", "p"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert (
        main([str(dataset), "--session", "resume", "--group", "zz-group-secret"]) == 0
    )
    labels_after = sum(
        1
        for path in (dataset / "labels").glob("*.jsonl")
        for line in path.read_text().splitlines()[1:]
        if line
    )
    assert labels_after == labels_before + 1
    assert verify_dataset(dataset) == []


def test_eof_during_reason_does_not_write_choice(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path / "data")
    answers = iter(["a"])

    def read(_prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", read)
    assert (
        main(
            [
                str(dataset),
                "--session",
                "cut",
                "--group",
                "zz-group-secret",
                "--seed",
                "2",
            ]
        )
        == 0
    )
    saved = json.loads((dataset / "sessions" / "duel-cut.json").read_text())
    assert saved["cursor"] == 0 and saved["labels"] == []
    assert not (dataset / "manifest.toml").read_text().count("[[label_batches]]")


def test_piped_stdin_pauses_session(tmp_path):
    dataset = _dataset(tmp_path / "piped")
    result = subprocess.run(  # noqa: S603 - Test executes the calibration CLI with controlled fixture arguments.
        [
            sys.executable,
            "-m",
            "varde_dev.calibrate",
            "duel",
            str(dataset),
            "--session",
            "pipe",
            "--group",
            "zz-group-secret",
            "--seed",
            "7",
        ],
        input="p\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    saved = json.loads((dataset / "sessions" / "duel-pipe.json").read_text())
    assert saved["paused"] is True
    assert saved["cursor"] == 0
    assert "Resume with:" in result.stdout


def test_seed_reproduces_first_side_assignment(tmp_path, monkeypatch, capsys):
    displays = []
    for index in range(2):
        dataset = _dataset(tmp_path / f"seed-{index}")
        monkeypatch.setattr("builtins.input", lambda _prompt="": "p")
        assert (
            main(
                [
                    str(dataset),
                    "--session",
                    "same",
                    "--group",
                    "zz-group-secret",
                    "--seed",
                    "31",
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        displays.append(
            output.split("Compare implementations\n\n", 1)[1].split("\n\nPaused", 1)[0]
        )
    assert displays[0] == displays[1]


def _solo_dataset(path: Path) -> Path:
    init_dataset(path)
    import_dataset(
        path,
        items=[
            {
                "id": "solo-item",
                "language": "python",
                "task_id": "solo-task",
                "pair_group_id": "solo",
                "text": "solo code",
                "license": "MIT",
                "split": "dev",
            }
        ],
        units=[],
        tasks=[{"id": "solo-task", "description": "Solo task"}],
    )
    return path


def test_solo_group_is_reported_and_group_selection_is_clear(tmp_path, capsys):
    dataset = _solo_dataset(tmp_path / "solo")
    assert main([str(dataset), "--session", "solo", "--group", "solo"]) == 0
    output = capsys.readouterr().out
    assert "Skipping group solo: fewer than 2 items." in output
    assert "No duel available for group solo" in output


def test_second_group_can_be_selected_and_labelled(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path / "second", groups=("g", "g", "h", "h"))
    answers = iter(["a", "", "p"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert (
        main(
            [
                str(dataset),
                "--session",
                "second",
                "--group",
                "h",
                "--max-matches",
                "1",
                "--seed",
                "3",
            ]
        )
        == 0
    )
    labels = [
        json.loads(line)
        for path in (dataset / "labels").glob("*.jsonl")
        for line in path.read_text().splitlines()[1:]
        if line
    ]
    units = {unit["id"]: unit for unit in _jsonl(dataset / "units.jsonl")}
    assert len(labels) == 1
    assert units[labels[0]["unit_id"]]["pair_group_id"] == "h"


def test_skip_and_max_matches_pause_without_advancing_label_cursor(
    tmp_path, monkeypatch
):
    dataset = _dataset(tmp_path / "skip", groups=("g", "g", "g", "g"))
    answers = iter(["s", "a", "", "p"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert (
        main(
            [
                str(dataset),
                "--session",
                "skip",
                "--group",
                "g",
                "--max-matches",
                "1",
                "--seed",
                "8",
            ]
        )
        == 0
    )
    saved = json.loads((dataset / "sessions" / "duel-skip.json").read_text())
    assert saved["cursor"] == 1
    assert len(saved["skipped"]) == 1
    assert saved["paused"] is True


def test_choice_eof_does_not_write_synthetic_pair_unit(tmp_path, monkeypatch):
    dataset = init_dataset(tmp_path / "no-write")
    items = [
        {
            "id": f"item-{index}",
            "language": "python",
            "task_id": "task",
            "pair_group_id": "group",
            "text": f"code {index}",
            "license": "MIT",
            "split": "dev",
        }
        for index in range(3)
    ]
    units = [
        {
            "id": "existing-pair",
            "kind": "pair",
            "item_ids": ["item-1", "item-2"],
            "pair_group_id": "group",
            "task_id": "task",
            "split": "dev",
        }
    ]
    import_dataset(
        dataset,
        items=items,
        units=units,
        tasks=[{"id": "task", "description": "Compare"}],
    )
    before = (dataset / "units.jsonl").read_bytes()

    def eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert (
        main([str(dataset), "--session", "eof", "--group", "group", "--seed", "1"]) == 0
    )
    assert (dataset / "units.jsonl").read_bytes() == before


def test_invalid_input_and_resume_keep_pending_side(tmp_path, monkeypatch, capsys):
    dataset = _dataset(tmp_path / "pending")
    presentations = []
    attempt = 0

    def invalid_then_pause(_prompt=""):
        nonlocal attempt
        if _prompt.startswith("Choose"):
            output = capsys.readouterr().out
            presentations.append(output.rsplit("A:\n", 1)[1].split("\n\nB:\n", 1)[0])
            attempt += 1
            return "invalid" if attempt == 1 else "p"
        return ""

    monkeypatch.setattr("builtins.input", invalid_then_pause)
    assert (
        main(
            [
                str(dataset),
                "--session",
                "pending",
                "--group",
                "zz-group-secret",
                "--seed",
                "19",
            ]
        )
        == 0
    )
    assert presentations[0] == presentations[1]
    first = presentations[-1]
    monkeypatch.setattr("builtins.input", lambda _prompt="": "p")
    assert (
        main([str(dataset), "--session", "pending", "--group", "zz-group-secret"]) == 0
    )
    output = capsys.readouterr().out
    resumed = output.rsplit("A:\n", 1)[1].split("\n\nB:\n", 1)[0]
    assert resumed == first


def test_seed_reproduces_multiple_side_assignments(tmp_path, monkeypatch, capsys):
    sequences = []
    for index in range(2):
        dataset = _dataset(tmp_path / f"multi-seed-{index}")
        shown = []

        def answer(prompt="", shown=shown):
            if prompt.startswith("Choose"):
                output = capsys.readouterr().out
                shown.append(output.rsplit("A:\n", 1)[1].split("\n\nB:\n", 1)[0])
                return "a"
            return ""

        monkeypatch.setattr("builtins.input", answer)
        assert (
            main(
                [
                    str(dataset),
                    "--session",
                    "multi",
                    "--group",
                    "zz-group-secret",
                    "--max-matches",
                    "4",
                    "--seed",
                    "31",
                ]
            )
            == 0
        )
        sequences.append(shown)
    assert len(sequences[0]) == 4
    assert sequences[0] == sequences[1]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()[1:] if line]
