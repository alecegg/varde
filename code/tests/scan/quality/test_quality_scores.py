"""The TEMP quality_scores table: rows per snapshot, deterministic, index untouched."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).parents[2] / "quality_gate" / "fixtures"
sys.path.insert(0, str(_GATE))

from gate_calibration import load_gate_test_calibration  # noqa: E402
from gate_snapshots import LANGUAGES, SNAPSHOTS  # noqa: E402
from varde_code.extract.provider import CodeExtractionProvider  # noqa: E402
from varde_code.index.build import build  # noqa: E402
from varde_code.index.paths import repo_db_path  # noqa: E402
from varde_code.parse import parse_source  # noqa: E402
from varde_code.query import modes  # noqa: E402
from varde_code.scan.quality_scores import (  # noqa: E402
    COLUMNS,
    build_quality_rows,
    compute_scope_score,
    materialize_quality_scores,
)


@pytest.fixture(autouse=True, scope="session")
def _grammars() -> None:
    for grammar in ("python", "typescript", "tsx", "csharp"):
        try:
            parse_source(grammar, "value\n")
        except RuntimeError as error:
            pytest.skip(f"tree-sitter grammar cache unavailable: {error}")


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    return tmp_path / "repo"


def _write_and_index(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    build(root, CodeExtractionProvider())


def _table(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT * FROM temp.quality_scores ORDER BY rowid").fetchall()


def _read_only(root: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{repo_db_path(root).resolve()}?mode=ro", uri=True)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("language", LANGUAGES)
def test_rows_cover_scope_files_and_functions(language, repo):
    snapshot = SNAPSHOTS[language]
    calibration = load_gate_test_calibration()
    _write_and_index(repo, snapshot.files)
    conn = _read_only(repo)
    try:
        rows = materialize_quality_scores(conn, repo, calibration, workers=1)
        stored = _table(conn)
    finally:
        conn.close()

    assert len(stored) == len(rows)
    by_level = {
        level: [r for r in rows if r.level == level]
        for level in ("scope", "file", "function")
    }
    assert len(by_level["scope"]) == 1
    assert {r.path for r in by_level["file"]} == set(snapshot.files)
    assert by_level["function"]
    assert {r.calibration_id for r in rows} == {calibration.id}
    assert {r.metric_version for r in rows} == {calibration.formula}
    files = {r.path: r for r in by_level["file"]}
    debt_score = files[snapshot.path("debt")].score
    clean_score = files[snapshot.path("clean")].score
    assert debt_score is not None and clean_score is not None
    assert debt_score < clean_score
    assert files[snapshot.path("floor_exempt")].exempt
    assert all(r.language for r in by_level["file"])
    assert len(stored[0]) == len(COLUMNS)


def test_row_order_is_deterministic(repo):
    snapshot = SNAPSHOTS["python"]
    calibration = load_gate_test_calibration()
    _write_and_index(repo, snapshot.files)
    first, records = compute_scope_score(repo, calibration, workers=1)
    again, _ = compute_scope_score(repo, calibration, workers=2)

    rows = build_quality_rows(first, records, calibration)
    assert rows == build_quality_rows(again, list(reversed(records)), calibration)
    assert rows[0].level == "scope"
    file_paths = [str(r.path) for r in rows if r.level == "file"]
    assert file_paths == sorted(file_paths)


def test_table_is_temp_and_leaves_the_index_file_unchanged(repo):
    snapshot = SNAPSHOTS["csharp"]
    _write_and_index(repo, snapshot.files)
    before = _digest(repo_db_path(repo))
    conn = _read_only(repo)
    try:
        materialize_quality_scores(conn, repo, load_gate_test_calibration(), workers=1)
        in_main = conn.execute(
            "SELECT count(*) FROM main.sqlite_master WHERE name = 'quality_scores'"
        ).fetchone()[0]
        in_temp = conn.execute(
            "SELECT count(*) FROM temp.sqlite_master WHERE name = 'quality_scores'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert (in_main, in_temp) == (0, 1)
    assert _digest(repo_db_path(repo)) == before


def test_tsx_maps_to_typescript_when_calibration_lacks_it(repo):
    from varde_code.quality_score.calibration import load_calibration

    snapshot = SNAPSHOTS["typescript"]
    placeholder = Path(__file__).parents[3] / (
        "src/varde_code/quality_score/calibration/placeholder.toml"
    )
    calibration = load_calibration(placeholder)
    assert "tsx" not in calibration.languages
    _write_and_index(repo, snapshot.files)
    scope, records = compute_scope_score(repo, calibration, workers=1)
    tsx = next(
        r
        for r in build_quality_rows(scope, records, calibration)
        if r.path == snapshot.path("tsx")
    )

    assert tsx.language == "tsx"
    assert tsx.score is not None


def test_syntax_error_file_stays_scored_with_the_parse_diagnostic(repo):
    snapshot = SNAPSHOTS["python"]
    calibration = load_gate_test_calibration()
    files = {**snapshot.files, snapshot.path("clean"): snapshot.syntax_error}
    _write_and_index(repo, files)
    scope, records = compute_scope_score(repo, calibration, workers=1)
    row = next(
        r
        for r in build_quality_rows(scope, records, calibration)
        if r.path == snapshot.path("clean")
    )

    assert "parse contains errors" in row.diagnostics
    assert row.score is not None
