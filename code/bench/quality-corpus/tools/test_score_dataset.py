from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import score_dataset  # noqa: E402, RUF100

PYTHON_SOURCE = (
    "def add(a, b):\n    return a + b\n\n\n"
    "def pick(items, key):\n    for item in items:\n        if item == key:\n"
    "            return item\n    return None\n"
)


def _write_dataset(root: Path, rows: list[dict]) -> Path:
    dataset = root / "dataset"
    dataset.mkdir()
    lines = [{"record_type": "items", "schema_version": 1}, *rows]
    (dataset / "items.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in lines), encoding="utf-8"
    )
    return dataset


def _item(item_id: str, language: str, split: str = "dev", text: str = PYTHON_SOURCE):
    return {"id": item_id, "language": language, "split": split, "text": text}


def _run(dataset: Path, out: Path, *extra: str) -> int:
    argv = ["score_dataset.py", "--dataset", str(dataset), "--out", str(out), *extra]
    old = sys.argv
    sys.argv = argv
    try:
        return score_dataset.main()
    finally:
        sys.argv = old


def _dataset(tmp_path: Path) -> Path:
    return _write_dataset(
        tmp_path,
        [
            _item("p2:b", "python"),
            _item("p1:a", "python"),
            _item("p3:a", "python", split="test"),
            _item("x1:a", "cobol"),
        ],
    )


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    assert _run(dataset, tmp_path / "one") == 0  # noqa: S101 - pytest assertion.
    assert _run(dataset, tmp_path / "two") == 0  # noqa: S101 - pytest assertion.
    for name in score_dataset.OUTPUT_FILES:
        assert (tmp_path / "one" / name).read_bytes() == (  # noqa: S101
            tmp_path / "two" / name
        ).read_bytes()


def test_scores_sorted_integer_and_test_split_not_read(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    _run(dataset, tmp_path / "out")
    rows = [
        json.loads(line)
        for line in (tmp_path / "out/scores.jsonl").read_text().splitlines()
    ]
    assert [row["id"] for row in rows] == ["p1:a", "p2:b"]  # noqa: S101
    assert all(isinstance(row["score"], int) for row in rows)  # noqa: S101
    assert all(isinstance(row["debt"], int) for row in rows)  # noqa: S101


def test_unscored_item_is_listed_with_reason(tmp_path: Path, capsys) -> None:
    dataset = _dataset(tmp_path)
    _run(dataset, tmp_path / "out")
    skipped = [
        json.loads(line)
        for line in (tmp_path / "out/unscored.jsonl").read_text().splitlines()
    ]
    assert [row["id"] for row in skipped] == ["x1:a"]  # noqa: S101
    assert "unsupported language cobol" in skipped[0]["reason"]  # noqa: S101
    assert "unscored: x1:a" in capsys.readouterr().out  # noqa: S101
    run = json.loads((tmp_path / "out/run.json").read_text())
    assert run["unscored"] == 1 and run["commit"]  # noqa: S101


def test_check_determinism_passes_across_fresh_process(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    assert _run(dataset, tmp_path / "out", "--check-determinism") == 0  # noqa: S101


def test_check_determinism_fails_when_second_run_differs(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = _dataset(tmp_path)
    monkeypatch.setattr(
        score_dataset, "differing_files", lambda first, second: ["scores.jsonl"]
    )
    assert _run(dataset, tmp_path / "out", "--check-determinism") == 1  # noqa: S101


def test_missing_dataset_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        score_dataset.read_items(tmp_path, frozenset({"dev"}))
