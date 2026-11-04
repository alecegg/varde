"""Shared helpers for the scan-gate attack suite: snapshots, calibration, scoring.

The fixture modules live in ``fixtures/`` and are imported by their unique names.
``score_repo`` writes a snapshot, builds the fast index, runs the quality pass and
scores the stored facts merged with their L3 measures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
if str(FIXTURES) not in sys.path:
    sys.path.insert(0, str(FIXTURES))

from gate_calibration import (  # noqa: E402
    load_gate_test_calibration,
)
from gate_snapshots import LANGUAGES, SNAPSHOTS, Snapshot  # noqa: E402
from varde_code.extract.provider import CodeExtractionProvider  # noqa: E402
from varde_code.index.build import build  # noqa: E402
from varde_code.parse import parse_source  # noqa: E402
from varde_code.quality_pass.pass_ import (  # noqa: E402
    read_facts,
    read_measures,
    run_quality_pass,
)
from varde_code.quality_score import score_scope  # noqa: E402
from varde_code.quality_score.scoring import ScopeScore  # noqa: E402
from varde_code.query import modes  # noqa: E402

_MEASURE_KEYS = (
    "depth",
    "fan_out",
    "tree_size",
    "callers_in_module",
    "fragment_scope",
)
_GRAMMARS = ("python", "typescript", "tsx", "csharp")


@pytest.fixture(autouse=True, scope="session")
def _warm_grammar_cache() -> None:
    for grammar in _GRAMMARS:
        try:
            parse_source(grammar, "value\n")
        except RuntimeError as error:
            pytest.skip(f"tree-sitter grammar cache unavailable for {grammar}: {error}")


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Return an empty repo root with the config dir and index service isolated."""
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    return tmp_path / "repo"


@pytest.fixture(params=LANGUAGES)
def snapshot(request: pytest.FixtureRequest) -> Snapshot:
    return SNAPSHOTS[request.param]


@pytest.fixture(scope="session")
def gate_calibration():
    return load_gate_test_calibration()


def write_files(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def merged_facts(root: Path) -> list[dict]:
    """Return stored facts with their L3 measures merged in, ready for scoring."""
    measures = {record["path"]: record for record in read_measures(root)}
    records = []
    for fact in read_facts(root):
        measure = measures[fact["path"]]
        per_function = measure["functions"]
        functions = [
            {**function, **{k: per_function[function["id"]][k] for k in _MEASURE_KEYS}}
            for function in fact["functions"]
        ]
        records.append(
            {
                **fact,
                "functions": functions,
                "module": measure["module"],
                "structure_confidence": measure["structure_confidence"],
            }
        )
    return records


def score_repo(root: Path, files: dict[str, str], calibration) -> ScopeScore:
    """Write ``files``, run the index and quality pass, and score the scope."""
    write_files(root, files)
    build(root, CodeExtractionProvider())
    run_quality_pass(root, workers=1)
    return score_scope(merged_facts(root), calibration)


def file_scores(scope: ScopeScore) -> dict:
    return {file.path: file for file in scope.files}
