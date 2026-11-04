import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from export_pairs import export

EXPORT_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "export_pairs.py"


def test_export_writes_dataset_store_layout_with_stable_opaque_pair_group(
    tmp_path: Path,
) -> None:
    items = tmp_path / "items" / "python" / "dev" / "task-group"
    items.mkdir(parents=True)
    (items / "left.py").write_text("def answer(): return 1\n")
    (items / "right.py").write_text("def answer(): return 1\n")
    (items / "behaviour_test.py").write_text(
        "import solution\nassert solution.answer() == 1\n"
    )
    (items / "pair.json").write_text(
        json.dumps(
            {
                "left": "left.py",
                "right": "right.py",
                "task_id": "task-group",
                "language": "python",
            }
        )
    )
    (items / "manifest.toml").write_text('license = "MIT"\n')
    output = tmp_path / "dataset"
    assert export(tmp_path / "items", output) == 1
    pair_dir = next(output.iterdir())
    manifest = tomllib.loads((pair_dir / "manifest.toml").read_text())
    assert (pair_dir / "a.py").exists()
    assert (pair_dir / "b.py").exists()
    assert (pair_dir / "behaviour_test.py").exists()
    assert manifest["pair_group_id"] == "task-group"
    assert "padded_evidence" not in manifest
    assert manifest["left"] == "a.py"
    assert manifest["license"] == "MIT"
    assert (
        manifest["sha256"]["a"]
        == hashlib.sha256((pair_dir / "a.py").read_bytes()).hexdigest()
    )
    assert (
        manifest["sha256"]["b"]
        == hashlib.sha256((pair_dir / "b.py").read_bytes()).hexdigest()
    )
    assert (
        manifest["sha256"]["behaviour_test"]
        == hashlib.sha256((pair_dir / "behaviour_test.py").read_bytes()).hexdigest()
    )
    assert len(pair_dir.name) == 32
    other_items = tmp_path / "elsewhere" / "items"
    other_pair = other_items / "different-path" / "pair"
    other_pair.mkdir(parents=True)
    for filename in ("left.py", "right.py", "behaviour_test.py", "pair.json"):
        (other_pair / filename).write_bytes((items / filename).read_bytes())
    other_output = tmp_path / "other-dataset"
    assert export(other_items, other_output) == 1
    assert next(other_output.iterdir()).name == pair_dir.name


def test_export_cli_reports_success_and_invalid_pair(tmp_path: Path) -> None:
    items = tmp_path / "items"
    pair = items / "pair"
    pair.mkdir(parents=True)
    (pair / "a.py").write_text("pass\n")
    (pair / "b.py").write_text("pass\n")
    (pair / "behaviour_test.py").write_text("pass\n")
    (pair / "pair.json").write_text(json.dumps({"left": "a.py", "right": "b.py"}))
    result = subprocess.run(  # noqa: S603 - Runs the export CLI against controlled fixture data.
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            "--items",
            str(items),
            "--output",
            str(tmp_path / "out"),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0
    (pair / "pair.json").write_text(json.dumps({"left": "missing.py", "right": "b.py"}))
    failed = subprocess.run(  # noqa: S603 - Verifies the export CLI rejects invalid fixture data.
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            "--items",
            str(items),
            "--output",
            str(tmp_path / "bad"),
        ],
        check=False,
        capture_output=True,
    )
    assert failed.returncode == 1


@pytest.mark.parametrize(
    ("task_id", "expected_evidence"),
    [("invoice-aging", False), ("order-quote", True)],
)
def test_category_b_padded_pair_exports_tier_evidence(
    tmp_path: Path, task_id: str, expected_evidence: bool
) -> None:
    items = tmp_path / "items" / "python" / "b" / task_id
    items.mkdir(parents=True)
    for name in ("sensible.py", "tiny.py", "padded.py", "behaviour_test.py"):
        (items / name).write_text(f"# {name}\n")
    pairs = [
        {"left": "sensible.py", "right": "tiny.py"},
        {"left": "sensible.py", "right": "padded.py"},
    ]
    (items / "pair.json").write_text(
        json.dumps({"task": task_id, "language": "python", "pairs": pairs})
    )
    output = tmp_path / "dataset"
    assert export(tmp_path / "items", output) == 2
    manifests = [
        tomllib.loads(path.read_text()) for path in output.glob("*/manifest.toml")
    ]
    assert sorted("padded_evidence" in manifest for manifest in manifests) == [
        False,
        True,
    ]
    padded = next(manifest for manifest in manifests if "padded_evidence" in manifest)
    assert padded["padded_evidence"] is expected_evidence
