import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from varde_dev.calibrate.cli import main as calibrate_main


def make_exported_pair(
    pair_root: Path,
    pair_id: str,
    options: dict[str, object] | None = None,
) -> Path:
    settings = options or {}
    pair_dir = pair_root / pair_id
    pair_dir.mkdir(parents=True)
    files = {
        "a.py": "def sort_a(values): return sorted(values)\n",
        "b.py": "def sort_b(values): return values\n",
        "behaviour_test.py": "assert sort_a([2, 1]) == [1, 2]\n",
    }
    for name, content in files.items():
        (pair_dir / name).write_text(content, encoding="utf-8")

    fields = {
        "id": pair_id,
        "pair_group_id": settings.get("pair_group_id", "task-group-opaque"),
        "language": settings.get("language", "python"),
        "task": settings.get("task", "Sort a list of values"),
        "left": "a.py",
        "right": "b.py",
        "behaviour_test": "behaviour_test.py",
    }
    license_id = settings.get("license_id", "MIT")
    if license_id is not None:
        fields["license"] = license_id
    omit = settings.get("omit")
    if isinstance(omit, str):
        fields.pop(omit, None)
    text = "".join(f"{key} = {json.dumps(value)}\n" for key, value in fields.items())
    text += "\n[sha256]\n"
    hashes = {
        "a": hashlib.sha256(files["a.py"].encode()).hexdigest(),
        "b": hashlib.sha256(files["b.py"].encode()).hexdigest(),
        "behaviour_test": hashlib.sha256(
            files["behaviour_test.py"].encode()
        ).hexdigest(),
    }
    if settings.get("bad_hash"):
        hashes["a"] = "0" * 64
    text += "".join(f"{key} = {json.dumps(value)}\n" for key, value in hashes.items())
    (pair_dir / "manifest.toml").write_text(text, encoding="utf-8")
    return pair_dir


def test_init_import_verify_export_end_to_end(tmp_path):
    dataset = tmp_path / "dataset"
    pairs = tmp_path / "golden-export"
    pairs.mkdir()
    make_exported_pair(pairs, "opaque-pair-dev")
    regression_pairs = tmp_path / "regression-export"
    regression_pairs.mkdir()
    make_exported_pair(
        regression_pairs,
        "opaque-pair-regression",
        {"pair_group_id": "another-group", "task": "Handle a value"},
    )

    assert calibrate_main(["init", str(dataset)]) == 0
    assert (dataset / "manifest.toml").is_file()
    assert (dataset / "items.jsonl").is_file()
    assert (
        calibrate_main(
            ["import", str(dataset), "--pairs", str(pairs), "--split", "dev"]
        )
        == 0
    )
    assert (
        calibrate_main(
            [
                "import",
                str(dataset),
                "--pairs",
                str(regression_pairs),
                "--split",
                "regression",
            ]
        )
        == 0
    )
    assert calibrate_main(["verify", str(dataset)]) == 0
    task_records = [
        json.loads(line)
        for line in (dataset / "tasks.jsonl").read_text().splitlines()[1:]
    ]
    test_reference = task_records[0]["behaviour_tests"][0]
    stored_test = dataset / test_reference["path"]
    assert (
        stored_test.read_text()
        == (pairs / "opaque-pair-dev" / "behaviour_test.py").read_text()
    )
    stored_test.write_text("tampered test\n", encoding="utf-8")
    assert calibrate_main(["verify", str(dataset)]) == 1
    stored_test.write_text(
        (pairs / "opaque-pair-dev" / "behaviour_test.py").read_text(), encoding="utf-8"
    )

    output = tmp_path / "dev.jsonl"
    assert (
        calibrate_main(
            ["export", str(dataset), "--split", "dev", "--output", str(output)]
        )
        == 0
    )
    exported = [json.loads(line) for line in output.read_text().splitlines()[1:]]
    assert [item["id"] for item in exported] == [
        "opaque-pair-dev:a",
        "opaque-pair-dev:b",
    ]
    assert all(item["split"] == "dev" for item in exported)

    item_file = dataset / "items.jsonl"
    rows = item_file.read_text().splitlines()
    item = json.loads(rows[1])
    item["text"] = "tampered"
    rows[1] = json.dumps(item)
    item_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert calibrate_main(["verify", str(dataset)]) == 1


@pytest.mark.parametrize(
    ("overrides", "omit", "message"),
    [
        ({"language": "not a language"}, None, "invalid language"),
        ({}, "task", "requires task"),
        ({}, "pair_group_id", "requires pair_group_id"),
        ({}, None, "license"),
        ({}, None, "content sha256 mismatch"),
    ],
)
def test_import_rejects_invalid_export_manifest(
    tmp_path, capsys, overrides, omit, message
):
    dataset = tmp_path / "dataset"
    assert calibrate_main(["init", str(dataset)]) == 0
    pair_root = tmp_path / "pairs"
    pair_root.mkdir()
    options: dict[str, object] = {"bad_hash": message == "content sha256 mismatch"}
    if message == "license":
        options["license_id"] = None
    if omit:
        options["omit"] = omit
    options.update(overrides)
    make_exported_pair(pair_root, "opaque-invalid", options)

    assert calibrate_main(["import", str(dataset), "--pairs", str(pair_root)]) == 1
    error = capsys.readouterr().err
    assert message in error
    if message == "license":
        assert 'add license = "MIT"' in error


def test_import_rejects_duplicate_pair_and_loads_sample_when_available(
    tmp_path, capsys, monkeypatch
):
    dataset = tmp_path / "dataset"
    pair_root = tmp_path / "pairs"
    pair_root.mkdir()
    make_exported_pair(pair_root, "opaque-duplicate")
    assert calibrate_main(["init", str(dataset)]) == 0
    assert calibrate_main(["import", str(dataset), "--pairs", str(pair_root)]) == 0
    assert calibrate_main(["import", str(dataset), "--pairs", str(pair_root)]) == 1
    assert "duplicate" in capsys.readouterr().err

    monkeypatch.setitem(sys.modules, "varde_dev.calibrate.sample", None)
    assert calibrate_main(["import", str(dataset), "--sample"]) == 1
    assert "built-in sample dataset is not installed" in capsys.readouterr().err

    sample_root = tmp_path / "sample"
    sample_root.mkdir()
    make_exported_pair(sample_root, "opaque-sample")
    sample_module = ModuleType("varde_dev.calibrate.sample")
    sample_module.dataset_dir = lambda: sample_root
    monkeypatch.setitem(sys.modules, "varde_dev.calibrate.sample", sample_module)
    sample_dataset = tmp_path / "sample-dataset"
    assert calibrate_main(["init", str(sample_dataset)]) == 0
    assert calibrate_main(["import", str(sample_dataset), "--sample"]) == 0
    assert calibrate_main(["verify", str(sample_dataset)]) == 0


def test_import_accepts_existing_task_and_rejects_changed_description(tmp_path, capsys):
    dataset = tmp_path / "dataset"
    assert calibrate_main(["init", str(dataset)]) == 0

    first_pairs = tmp_path / "first-pair"
    first_pairs.mkdir()
    make_exported_pair(first_pairs, "opaque-first")
    assert calibrate_main(["import", str(dataset), "--pairs", str(first_pairs)]) == 0

    second_pairs = tmp_path / "second-pair"
    second_pairs.mkdir()
    make_exported_pair(second_pairs, "opaque-second")
    assert calibrate_main(["import", str(dataset), "--pairs", str(second_pairs)]) == 0

    changed_pairs = tmp_path / "changed-pair"
    changed_pairs.mkdir()
    make_exported_pair(
        changed_pairs,
        "opaque-changed",
        {"task": "A changed task description"},
    )
    assert calibrate_main(["import", str(dataset), "--pairs", str(changed_pairs)]) == 1
    assert "different description" in capsys.readouterr().err
