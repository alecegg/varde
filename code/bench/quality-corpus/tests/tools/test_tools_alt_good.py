"""Behaviour checks for the optional alt-good preference versions.

Alt-good versions are behaviour-identical to sensible in a different style, so
they are optional, checked with the layered sensible limits, and exported as
preference-neutral pairs that carry no quality direction.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import item_targets
import pytest
from behaviour_runner import pair_versions
from export_pairs import export

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
CHECKER = TOOLS / "item_spec_check.py"
SOURCE_ITEM = ROOT / "items" / "python" / "b" / "order-quote"
PYTHON_RICH = ("order-quote", "clinic-booking", "shift-pay", "rental-quote")

sys.path.insert(0, str(ROOT / "counts"))
import count_items  # noqa: E402, RUF100 - counts path must be on sys.path first


def opaque(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def copy_item(tmp_path: Path) -> Path:
    item = tmp_path / "order-quote"
    shutil.copytree(SOURCE_ITEM, item)
    pair_path = item / "pair.json"
    pair = json.loads(pair_path.read_text())
    pair["pairs"] = [
        entry for entry in pair["pairs"] if entry.get("right_role") != "alt-good"
    ]
    pair_path.write_text(json.dumps(pair))
    profile_path = item / "spec-profile.toml"
    profile_path.write_text('profile = "layered"\n')
    for name in ("alt-pipeline.py", "alt-table.py", "alt-class.py"):
        (item / name).unlink(missing_ok=True)
    return item


def add_alt(item: Path, name: str, source: str | None = None) -> None:
    """Write an alt version, by default identical to sensible."""
    text = source if source is not None else (item / "sensible.py").read_text()
    (item / f"{name}.py").write_text(text)


def declare_alts(
    item: Path, declared: list[str], required: list[str] | None = None
) -> None:
    pair_path = item / "pair.json"
    pair = json.loads(pair_path.read_text())
    left_id = pair["pairs"][0]["left_id"]
    for name in declared:
        pair["pairs"].append(
            {
                "pair_id": opaque(f"{name}-pair"),
                "left_id": left_id,
                "right_id": opaque(name),
                "left": "sensible.py",
                "right": f"{name}.py",
                "left_role": "sensible",
                "right_role": "alt-good",
                "preference_neutral": True,
            }
        )
    pair_path.write_text(json.dumps(pair))
    if required is not None:
        (item / "spec-profile.toml").write_text(
            'profile = "layered"\nalts = ' + json.dumps(required) + "\n"
        )


def check(item: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - Runs the CLI under test against controlled arguments.
        [sys.executable, str(CHECKER), "--items", str(item), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ,
    )


def findings(result: subprocess.CompletedProcess) -> list[dict]:
    lines = result.stdout.splitlines()
    return [json.loads(line) for line in lines if line.startswith("{")]


def test_declared_alt_is_valid_and_measured(tmp_path: Path) -> None:
    item = copy_item(tmp_path)
    add_alt(item, "alt-pipeline")
    declare_alts(item, ["alt-pipeline"], required=["alt-pipeline"])
    result = check(item)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "alt-pipeline" in result.stdout
    assert pair_versions(json.loads((item / "pair.json").read_text()))[-1] == (
        "alt-pipeline.py"
    )


def test_absent_alts_are_allowed(tmp_path: Path) -> None:
    item = copy_item(tmp_path)
    assert check(item).returncode == 0


def test_alt_over_a_sensible_cap_is_flagged(tmp_path: Path) -> None:
    item = copy_item(tmp_path)
    add_alt(
        item,
        "alt-table",
        (item / "sensible.py").read_text() + "\n\ndef orphan_rows():\n    return 0\n",
    )
    declare_alts(item, ["alt-table"])
    result = check(item)
    assert result.returncode == 1
    kinds = {(finding["kind"], finding["version"]) for finding in findings(result)}
    assert ("alt_dead_code", "alt-table") in kinds
    assert ("alt_function_tokens", "alt-table") in kinds


def test_required_alt_missing_is_flagged(tmp_path: Path) -> None:
    item = copy_item(tmp_path)
    declare_alts(item, [], required=["alt-class"])
    result = check(item)
    assert result.returncode == 1
    assert any(
        finding["kind"] == "missing_alt" and finding["version"] == "alt-class"
        for finding in findings(result)
    )


def test_unknown_alt_name_is_rejected(tmp_path: Path) -> None:
    item = copy_item(tmp_path)
    declare_alts(item, [], required=["alt-nope"])
    result = check(item)
    assert result.returncode == 1
    assert any(
        finding["kind"] == "unknown_alt" and finding["version"] == "alt-nope"
        for finding in findings(result)
    )


def test_python_rich_items_still_check_clean() -> None:
    for task in PYTHON_RICH:
        result = check(ROOT / "items" / "python" / "b" / task)
        assert result.returncode == 0, result.stdout + result.stderr


def test_item_targets_shows_alt_rows_and_bands(tmp_path, capsys) -> None:
    item = copy_item(tmp_path)
    add_alt(item, "alt-pipeline")
    assert item_targets.main([str(item)]) == 0
    output = capsys.readouterr().out
    rows = {line.split()[0]: line for line in output.splitlines() if line.strip()}
    assert "alt-pipeline" in rows
    assert rows["alt-pipeline"].rstrip().endswith("ok")
    assert "alt-pipeline" in output.split("functions:")[1]
    broken = copy_item(tmp_path / "broken")
    (broken / "alt-table.py").write_text(
        (broken / "sensible.py").read_text() + "\n\ndef orphan_rows():\n    return 0\n"
    )
    assert item_targets.main([str(broken)]) == 0
    report = capsys.readouterr().out
    assert "alt-table" in report
    assert "drift" in report


EXPORT_SENSIBLE = "def solution(value):\n    return value + 1\n"


def export_pair(tmp_path: Path, pair: dict) -> dict:
    item = tmp_path / "items" / "python" / "b" / "order-quote"
    item.mkdir(parents=True)
    (item / "sensible.py").write_text(EXPORT_SENSIBLE)
    (item / "alt-pipeline.py").write_text(EXPORT_SENSIBLE)
    (item / "behaviour_test.py").write_text("import solution\n")
    (item / "pair.json").write_text(
        json.dumps({"task": "order-quote", "language": "python", "pairs": [pair]})
    )
    output = tmp_path / "dataset"
    assert export(tmp_path / "items", output) == 1
    return tomllib.loads((next(output.iterdir()) / "manifest.toml").read_text())


def alt_pair(**extra) -> dict:
    return {
        "left": "sensible.py",
        "right": "alt-pipeline.py",
        "left_role": "sensible",
        "right_role": "alt-good",
        **extra,
    }


def test_export_marks_alt_pairs_preference_neutral(tmp_path: Path) -> None:
    manifest = export_pair(tmp_path, alt_pair(preference_neutral=True))
    assert manifest["role"] == "alt-good"
    assert manifest["preference_neutral"] is True
    assert not {"direction", "label", "expected_direction"} & set(manifest)


def test_export_rejects_alt_good_without_preference_neutral(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        export_pair(tmp_path, alt_pair())


def test_checker_reports_alt_good_role_on_sensible(tmp_path: Path) -> None:
    item = copy_item(tmp_path)
    pair_path = item / "pair.json"
    data = json.loads(pair_path.read_text())
    data["pairs"][0]["left_role"] = "alt-good"
    pair_path.write_text(json.dumps(data))
    result = check(item)
    assert any(
        finding["kind"] == "alt_good_on_sensible" for finding in findings(result)
    )


def test_count_items_reports_alt_good_without_a_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "order-quote"
    directory.mkdir()
    for name in ("sensible", "alt-pipeline", "alt-table"):
        (directory / f"{name}.py").write_text("pass\n")
    pair = {
        "pairs": [
            {"right": "alt-pipeline.py", "right_role": "alt-good"},
            {"right": "alt-table.py", "right_role": "alt-good"},
            {"right": "missing.py", "right_role": "alt-good"},
        ]
    }
    assert count_items.alt_good_versions(directory, "python", pair) == 2
    row = {
        "a": 6,
        "b_small": 6,
        "b_rich": 4,
        "bprime": 2,
        "c": 6,
        "d": 4,
        "anchors": 2,
        "idiom": 2,
        "alt_good": 2,
    }
    monkeypatch.setattr(count_items, "toolchain", lambda _language: True)
    assert count_items.gaps({"python": row}, Path("unused.json"))["python"] == []
    assert "| 2 | complete" in count_items.render_report(
        {"python": row}, {"python": []}
    )
