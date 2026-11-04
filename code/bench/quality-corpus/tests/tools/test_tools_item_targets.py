"""Behaviour checks for the one-call item size target tool."""

import json
from pathlib import Path

import item_targets
import pytest
from item_spec_extract import SourceSyntaxError, extract

GO_SAMPLE = "package main\nfunc solution() {}\n"
VARIANTS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
SENSIBLE = """\
def solution(values):
    total = sum(values) + len(values)
    scaled = total * 3 - 7
    return finish(scaled) if scaled else total


def finish(value):
    rounded = value // 2 + 4
    capped = rounded * 2 - 1
    total = capped + rounded
    return total if total else rounded
"""


def write_item(root: Path, *, layered: bool, extension: str = ".py") -> Path:
    item = root / "invoice-aging"
    item.mkdir(parents=True)
    for name in VARIANTS:
        (item / f"{name}{extension}").write_text(
            "def solution(value):\n    return value\n"
        )
    if layered:
        (item / "spec-profile.toml").write_text('profile = "layered"\n')
    return item


def run(capsys, item: Path, *extra: str) -> str:
    assert item_targets.main([str(item), *extra]) == 0
    return capsys.readouterr().out


def section(output: str, title: str) -> dict[str, str]:
    """Read one printed section as name -> text, rejoining wrapped lines."""
    lines = output.splitlines()
    found: dict[str, str] = {}
    current = None
    for line in lines[lines.index(title) + 1 :]:
        if not line.startswith(" ") and line.endswith(":"):
            break
        if current is None and not line.startswith(" "):
            break
        name, separator, text = line.partition(":")
        if line.startswith(" ") and separator and not line.startswith("   "):
            current = name.strip()
            found[current] = text
        elif current is not None:
            found[current] += line
    return found


def test_layered_bands_come_from_the_profile(tmp_path, capsys):
    output = run(capsys, write_item(tmp_path, layered=True))
    targets = section(output, "targets:")
    assert "functions 28-72" in targets["tiny"]
    assert "rows <=10" in targets["tiny"]
    assert "forwarders >=3" in targets["namematched"]
    assert "functions 14-22" in targets["padded"]
    assert "helper tokens 30-130" in targets["padded"]


def test_small_tier_bands_differ_without_a_profile(tmp_path, capsys):
    output = run(capsys, write_item(tmp_path, layered=False))
    targets = section(output, "targets:")
    assert "functions 12-32" in targets["tiny"]
    assert "functions 7-20" not in targets["tiny"]
    assert "profile=small" in output


def test_monolith_function_floor_follows_sensible_tokens(tmp_path, capsys):
    item = write_item(tmp_path, layered=True)
    (item / "sensible.py").write_text(SENSIBLE)
    output = run(capsys, item)
    monolith = section(output, "targets:")["monolith"]
    assert "function tokens >200 and >" in monolith
    assert "file ceiling <=" in monolith


def test_missing_variants_are_listed_with_bands(tmp_path, capsys):
    item = tmp_path / "partial"
    item.mkdir()
    (item / "sensible.py").write_text(SENSIBLE)
    output = run(capsys, item)
    targets = section(output, "targets:")
    assert set(targets) == {"monolith", "tiny", "padded", "sizematched", "namematched"}
    assert "missing" in output
    assert "checker: findings need all six variants" in output


def test_json_mode_parses(tmp_path, capsys):
    output = run(capsys, write_item(tmp_path, layered=True), "--json")
    report = json.loads(output)
    assert report["language"] == "python"
    assert report["profile"] == "layered"
    assert report["variants"]["tiny"]["bands"]
    assert report["variants"]["tiny"]["functions"][0]["name"] == "solution"


def test_go_variant_rows_cap_follows_the_language(tmp_path, capsys):
    try:
        extract("go", GO_SAMPLE)
    except (RuntimeError, SourceSyntaxError) as error:
        pytest.skip(f"go grammar unavailable: {error}")
    item = write_item(tmp_path, layered=False, extension=".go")
    for name in VARIANTS:
        (item / f"{name}.go").write_text(GO_SAMPLE)
    output = run(capsys, item)
    assert "language=go" in output
    assert "rows <=6" in section(output, "targets:")["tiny"]


def test_usage_error_exits_two(tmp_path):
    with pytest.raises(SystemExit) as raised:
        item_targets.main([str(tmp_path / "absent")])
    assert raised.value.code == 2
