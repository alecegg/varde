import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items"
HYGIENE = ROOT / "tools" / "hygiene.py"
RESTRICTED = Path(
    os.environ.get(
        "VARDE_GOLDEN_RESTRICTED",
        "/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-17-quality-score-build/qs-golden-corpus/notes/restricted/golden",
    )
)
EXPECTED_SPLITS = {
    "structured-booking": "test-restricted",
    "structured-allowance": "dev",
    "structured-gratuity": "dev",
    "structured-distance": "test-restricted",
    "structured-cart-count": "test-restricted",
    "structured-temperature": "dev",
    "anchor-ledger": "dev",
    "anchor-queue": "test-restricted",
}
EXPECTED_DEFECTS = {
    "structured-booking": "long-parameter-list",
    "structured-allowance": "copy-paste",
    "structured-gratuity": "unclear-names",
    "structured-distance": "deep-nesting",
    "structured-cart-count": "monolith",
    "structured-temperature": "mutable-flags",
}


def task_directories(base: Path) -> dict[str, Path]:
    return {
        manifest_path.parent.name: manifest_path.parent
        for manifest_path in base.rglob("manifest.toml")
        if manifest_path.parent.name in EXPECTED_SPLITS
    }


def run_shared_test(directory: Path, side: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        test_root = Path(temporary)
        shutil.copyfile(side, test_root / "solution.py")
        shutil.copyfile(
            directory / "behaviour_test.py", test_root / "behaviour_test.py"
        )
        result = subprocess.run(
            [sys.executable, "behaviour_test.py"],
            cwd=test_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_items_have_expected_python_pairs_and_anchors() -> None:
    public = task_directories(ITEMS / "python" / "misc")
    restricted = task_directories(RESTRICTED)
    assert set(public) == {
        task for task, split in EXPECTED_SPLITS.items() if split == "dev"
    }
    assert set(restricted) == {
        task for task, split in EXPECTED_SPLITS.items() if split == "test-restricted"
    }

    categories = []
    defects = {}
    anchors = []
    for task, split in EXPECTED_SPLITS.items():
        directory = (public if split == "dev" else restricted)[task]
        manifest = tomllib.loads((directory / "manifest.toml").read_text())
        pair = json.loads((directory / "pair.json").read_text())
        category = manifest["category"]
        categories.append(category)
        assert category == ("e" if task.startswith("anchor-") else "a")
        assert pair["pair_group_id"] == manifest["pair_group_id"]
        assert len(pair["pair_group_id"]) == 24
        assert len(pair["pair_id"]) == 24
        assert "task" not in pair
        sides = (
            {"excellent.py", "poor.py"} if category == "e" else {"good.py", "bad.py"}
        )
        assert {path.name for path in directory.glob("*.py")} == sides | {
            "behaviour_test.py"
        }
        assert {pair["left"], pair["right"]} == sides
        side_paths = [directory / name for name in sorted(sides)]
        hashes = {hashlib.sha256(path.read_bytes()).digest() for path in side_paths}
        assert len(hashes) == 2
        assert (directory / "task.txt").is_file()
        for side in side_paths:
            run_shared_test(directory, side)
        hygiene_result = subprocess.run(  # noqa: S603 - Runs the repository hygiene CLI on a temporary fixture.
            [sys.executable, str(HYGIENE), "--items", str(directory), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert hygiene_result.returncode == 0, (
            hygiene_result.stdout + hygiene_result.stderr
        )

        if category == "a":
            defects[task] = manifest["dominant_defect"]
        else:
            assert pair["left_role"] == "excellent"
            assert pair["right_role"] == "poor"
            assert pair["left"] == "excellent.py"
            assert pair["right"] == "poor.py"
            anchors.append(pair)

        if split == "test-restricted":
            record = json.loads((directory / ".varde-split.json").read_text())
            assert record == {"task_id": task, "split": split}
            assert not directory.is_relative_to(ROOT)

    assert categories.count("a") == 6
    assert categories.count("e") == 2
    assert defects == EXPECTED_DEFECTS
    assert len(anchors) == 2
    assert all(pair["pair_group_id"] for pair in anchors)
