"""Editing a leaf file refreshes the persisted measures of files that reach it."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_files
from gate_snapshots import Snapshot
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.quality_pass.pass_ import read_measures, run_quality_pass
from varde_code.query import modes

# Each edit makes the leaf call a helper in a new file, which deepens the
# caller's call tree across files (an in-file or identity helper is folded).
_EDITS = {
    "python": {
        "gate/callee.py": (
            "from gate.helper import assist\n\n\n"
            "def compute(value):\n    return assist(value) + 1\n"
        ),
        "gate/helper.py": "def assist(value):\n    return value + 2\n",
    },
    "typescript": {
        "gate/callee.ts": (
            'import { assist } from "./helper";\n\n'
            "export function compute(value: number): number {\n"
            "  return assist(value) + 1;\n}\n"
        ),
        "gate/helper.ts": (
            "export function assist(value: number): number {\n  return value + 2;\n}\n"
        ),
    },
    "csharp": {
        "gate/Callee.cs": (
            "namespace Gate;\n\npublic static class Callee\n{\n"
            "    public static int Compute(int value)\n    {\n"
            "        return Helper.Assist(value) + 1;\n    }\n}\n"
        ),
        "gate/Helper.cs": (
            "namespace Gate;\n\npublic static class Helper\n{\n"
            "    public static int Assist(int value)\n    {\n"
            "        return value + 2;\n    }\n}\n"
        ),
    },
}


@pytest.fixture
def neutral_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Repo root on a neutral path (a ``test_*`` dir makes files test paths)."""
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    return tmp_path_factory.mktemp("inval") / "repo"


def _pass(root: Path, **options):
    build(root, CodeExtractionProvider())
    return run_quality_pass(root, workers=1, **options)


def _measures(root: Path) -> dict[str, dict]:
    return {record["path"]: record for record in read_measures(root)}


def test_leaf_edit_refreshes_dependents_and_matches_a_cold_run(
    snapshot: Snapshot, neutral_env: Path, tmp_path_factory: pytest.TempPathFactory
):
    root = neutral_env
    leaf, caller = snapshot.edge_callee, snapshot.edge_caller
    write_files(root, snapshot.files)
    _pass(root)
    before = _measures(root)

    write_files(root, _EDITS[snapshot.language])
    summary = _pass(root)
    after = _measures(root)

    assert {leaf, caller} <= set(summary.measures_recomputed)
    assert after[leaf] != before[leaf]
    assert after[caller] != before[caller]

    cold_root = tmp_path_factory.mktemp("cold") / "repo"
    write_files(cold_root, snapshot.files)
    write_files(cold_root, _EDITS[snapshot.language])
    _pass(cold_root)
    assert after == _measures(cold_root)


def test_unchanged_files_are_reused_when_nothing_is_edited(
    snapshot: Snapshot, neutral_env: Path
):
    root = neutral_env
    write_files(root, snapshot.files)
    _pass(root)
    summary = _pass(root)
    assert not summary.measures_recomputed
    assert summary.measures_reused == summary.file_count
