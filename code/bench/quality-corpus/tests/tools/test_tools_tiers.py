import json
import subprocess
import sys
from pathlib import Path

import pytest
from tiers import (
    _bank_coverage_problems,
    _profile_problems,
    _repo_item_id_problems,
    _restricted_other_category_ids,
    _rich_item_presence_problems,
    _tier_overlap_problems,
    padded_is_evidence,
    rich_tasks,
    tier_of,
)

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "tiers.py"
CORPUS = Path(__file__).resolve().parents[2]


def test_tier_overlap_problems() -> None:
    assert _tier_overlap_problems({"a", "b"}, {"b", "c"}) == [
        "task ids occur in both tiers: ['b']"
    ]
    assert _tier_overlap_problems({"a"}, {"b"}) == []


def test_bank_coverage_problems() -> None:
    assert _bank_coverage_problems({"a", "b"}, {"a", "extra"}, {"rich"}) == [
        "bank ids missing from tiers: ['b']",
        "unknown tier ids: ['extra']",
    ]


def test_rich_item_presence_problems() -> None:
    assert _rich_item_presence_problems({"a", "b"}, {"a"}, {"b"}) == []
    assert _rich_item_presence_problems({"a", "b"}, set(), set()) == [
        "rich task is absent from bank and repo items: a",
        "rich task is absent from bank and repo items: b",
    ]


def test_repo_item_id_problems() -> None:
    assert _repo_item_id_problems(["a", "ghost"], {"a"}) == [
        "unknown repo item task id: ghost"
    ]


def test_profile_problems() -> None:
    entries = [
        (Path("rich"), "r", False, False, None, ""),
        (Path("wrong"), "r", True, True, "default", ""),
        (Path("small"), "s", True, True, "layered", ""),
    ]
    assert _profile_problems(entries, {"r"}) == [
        "rich task lacks spec-profile.toml: rich",
        "rich task profile is not layered: wrong",
        "small task has spec-profile.toml: small",
    ]
    assert _profile_problems(
        [(Path("r"), "r", False, False, None, "restricted ")], {"r"}
    ) == ["rich restricted task lacks spec-profile.toml: r"]


def test_restricted_other_category_ids() -> None:
    directories = [
        Path("bank-a-python"),
        Path("rich-python"),
        Path("other-python"),
        Path("unmatched"),
    ]
    assert _restricted_other_category_ids(
        directories, {"python"}, {"bank-a", "rich"}, {"bank-a"}
    ) == ["other"]


def _write_tree(root: Path, failure: str | None = None) -> list[str]:
    bank_ids = ["bank-a", "bank-b"]
    bank = root / "bank.json"
    registry = root / "tiers.json"
    items = root / "items"
    store = root / "store"
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text(
        json.dumps({"languages": ["python"], "tasks": [{"id": x} for x in bank_ids]})
    )
    groups = {"small": bank_ids, "rich": ["order-quote"]}
    if failure == "rich-typo":
        groups["rich"].append("clinic-booking-typo")
    if failure == "overlap":
        groups["rich"].append("bank-a")
    if failure == "missing-bank-id":
        groups["small"].remove("bank-b")
    if failure == "unknown-tier-id":
        groups["small"].append("ghost")
    registry.write_text(
        json.dumps({"tiers": groups, "padded_evidence": {"small": False, "rich": True}})
    )
    rich_dir = items / "python" / "b" / "order-quote"
    rich_dir.mkdir(parents=True)
    (rich_dir / "spec-profile.toml").write_text('profile = "layered"\n')
    small_dir = items / "python" / "b" / "bank-a"
    small_dir.mkdir(parents=True)
    if failure == "bad-rich-profile":
        (rich_dir / "spec-profile.toml").unlink()
    if failure == "wrong-rich-profile":
        (rich_dir / "spec-profile.toml").write_text('profile = "default"\n')
    if failure == "small-profile":
        (small_dir / "spec-profile.toml").write_text('profile = "layered"\n')
    if failure == "unknown-item":
        (items / "python" / "b" / "ghost").mkdir()
    store.mkdir()
    restricted_rich = store / "test" / "bucket" / "order-quote-python"
    restricted_rich.mkdir(parents=True)
    (restricted_rich / "spec-profile.toml").write_text('profile = "layered"\n')
    if failure == "unknown-restricted":
        (store / "test" / "bucket" / "structured-booking-python").mkdir()
    if failure == "small-restricted-profile":
        small_restricted = store / "test" / "bucket" / "bank-a-python"
        small_restricted.mkdir()
        (small_restricted / "spec-profile.toml").write_text('profile = "layered"\n')
    return [
        sys.executable,
        str(SCRIPT),
        "--check",
        "--items",
        str(items),
        "--bank",
        str(bank),
        "--store",
        str(store),
        "--registry",
        str(registry),
    ]


def test_loader_answers_and_rejects_unknown_tasks() -> None:
    assert tier_of("invoice-aging") == "small"
    assert padded_is_evidence("invoice-aging") is False
    assert tier_of("order-quote") == "rich"
    assert padded_is_evidence("order-quote") is True
    assert tier_of("clinic-booking") == "rich"
    assert padded_is_evidence("clinic-booking") is True
    assert tier_of("shift-pay") == "rich"
    assert padded_is_evidence("shift-pay") is True
    assert tier_of("rental-quote") == "rich"
    assert padded_is_evidence("rental-quote") is True
    assert rich_tasks() == [
        "order-quote",
        "clinic-booking",
        "shift-pay",
        "rental-quote",
    ]
    with pytest.raises(KeyError):
        tier_of("missing-task")
    with pytest.raises(KeyError):
        padded_is_evidence("missing-task")


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("overlap", "both tiers"),
        ("missing-bank-id", "missing from tiers"),
        ("unknown-tier-id", "unknown tier ids"),
        ("rich-typo", "rich task is absent from bank and repo items"),
        ("unknown-item", "unknown repo item task id"),
        ("small-restricted-profile", "small restricted task has spec-profile.toml"),
        ("bad-rich-profile", "lacks spec-profile.toml"),
        ("wrong-rich-profile", "profile is not layered"),
        ("small-profile", "small task has spec-profile.toml"),
    ],
)
def test_check_cli_rejects_each_invalid_tree(
    tmp_path: Path, failure: str, expected: str
) -> None:
    result = subprocess.run(
        _write_tree(tmp_path, failure), check=False, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert expected in result.stderr


def test_check_cli_accepts_clean_tree_and_missing_store(tmp_path: Path) -> None:
    command = _write_tree(tmp_path)
    command[command.index("--store") + 1] = str(tmp_path / "absent")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 0
    assert "restricted store absent" in result.stdout


def test_check_cli_notes_restricted_dirs_from_other_categories(tmp_path: Path) -> None:
    result = subprocess.run(
        _write_tree(tmp_path, "unknown-restricted"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "note: 1 restricted dirs belong to other categories" in result.stdout


def test_check_cli_allows_unbanked_rich_ids_from_registry(tmp_path: Path) -> None:
    command = _write_tree(tmp_path)
    registry_path = Path(command[command.index("--registry") + 1])
    registry = json.loads(registry_path.read_text())
    registry["tiers"]["rich"].append("rich-extra")
    registry_path.write_text(json.dumps(registry))
    rich_item = tmp_path / "items" / "python" / "b" / "rich-extra"
    rich_item.mkdir()
    (rich_item / "spec-profile.toml").write_text('profile = "layered"\n')

    result = subprocess.run(command, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_check_cli_usage_exit_code(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], check=False, capture_output=True
    )
    assert result.returncode == 2


def test_check_cli_accepts_repository_tree() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--check",
            "--store",
            str(CORPUS / "missing-restricted-store"),
        ],
        cwd=CORPUS,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
