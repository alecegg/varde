"""Offline selection, mutation and routing checks for the c/d assembler."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from assemble_cd import (
    ROOT,
    AssemblyPaths,
    assemble_language,
    generate_mutations,
    license_allowed,
    place_item,
    select_mined,
    select_mutation_outputs,
    spdx_header,
)


def mined_record(index: int, license_name: str = "MIT") -> dict:
    return {
        "language": "python",
        "repo": f"example/repo-{index}",
        "license": license_name,
        "parent_sha": f"{index:040x}",
        "child_sha": f"{index + 1:040x}",
        "pin_sha": f"{index + 2:040x}",
        "changed_files": [f"src/{index}.py"],
        "changed_functions": ["calculate"],
        "intent_evidence": {"message": "Simplify calculation"},
        "pair_group_id": f"refactor-{index}",
    }


def test_selection_is_stable_diverse_and_license_filtered() -> None:
    records = [mined_record(i) for i in range(8)]
    records.extend(
        [mined_record(20, "GPL-3.0-only"), mined_record(21, "LicenseRef-Unknown")]
    )
    first = select_mined(records)
    assert first == select_mined(list(reversed(records)))
    assert len(first) == 6
    assert len({record["repo"] for record in first}) == 6
    assert all(license_allowed(record) for record in first)
    assert not license_allowed(mined_record(99, "GPL-3.0-only"))


def test_assembly_dry_run_counts_six_and_four_without_writing(tmp_path: Path) -> None:
    mined = tmp_path / "mined" / "python"
    mined.mkdir(parents=True)
    (mined / "sample.jsonl").write_text(
        "".join(json.dumps(mined_record(i)) + "\n" for i in range(6))
    )
    inputs = tmp_path / "mutation-inputs" / "python"
    inputs.mkdir(parents=True)
    provenance = []
    for index in range(4):
        name = f"{index:03d}-input.py"
        (inputs / name).write_text(
            f"def calculate(value):\n    result = value + {index}\n    return result\n"
        )
        provenance.append({"file": name, "license": "MIT", "repo": "fixture/source"})
    (inputs / "provenance.json").write_text(json.dumps({"inputs": provenance}))
    mutation_outputs = tmp_path / "mutation-outputs"
    generated, results = generate_mutations(
        "python", tmp_path / "mutation-inputs", mutation_outputs
    )
    assert generated >= 4
    assert results["valid"] == generated
    selected = select_mutation_outputs(mutation_outputs / "python")
    assert len(selected) == 4
    assert len({record["operator"] for record in selected}) == 4
    assert len({record["provenance"]["file"] for record in selected}) == 4
    assert (
        len(
            {
                hashlib.sha256(record["source"].encode()).hexdigest()
                for record in selected
            }
        )
        == 4
    )
    assert spdx_header("python", "MIT") == "# SPDX-License-Identifier: MIT"
    lock = tmp_path / "splits.lock"
    lock.write_text(json.dumps({"assignments": {}}))
    output = tmp_path / "items"
    counts = assemble_language(
        "python",
        AssemblyPaths(
            tmp_path / "mined",
            tmp_path / "mutation-inputs",
            mutation_outputs,
            output,
            lock,
            tmp_path / "cache",
            tmp_path / "restricted",
            True,
        ),
    )
    assert counts == (6, 4, 0)
    assert not output.exists()


def test_test_split_routes_outside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "pair.json").write_text("{}\n")
    restricted = tmp_path / "restricted"
    destination = place_item(
        source,
        "test-restricted",
        "opaque-id",
        tmp_path / "repo-items",
        repo,
        restricted,
    )
    assert destination.is_relative_to(restricted)
    assert not destination.is_relative_to(repo)
    assert json.loads((destination / ".varde-split.json").read_text()) == {
        "task_id": "opaque-id",
        "split": "test-restricted",
    }


def test_cli_bad_language_exits_two() -> None:
    result = subprocess.run(  # noqa: S603 - Runs the tested assembler with fixture arguments.
        [sys.executable, str(ROOT / "tools" / "assemble_cd.py"), "--lang", "klingon"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
