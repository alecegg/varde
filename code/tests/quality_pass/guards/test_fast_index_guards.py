from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from varde_code.extract.entity import extract_file
from varde_code.extract.langs import language_tables
from varde_code.index.build import build
from varde_code.index.incremental import refresh

GUARD_DIR = Path(__file__).parent
SCHEMA_PIN = json.loads((GUARD_DIR / "fast_index_schema.json").read_text())
ARTIFACT_PIN = json.loads((GUARD_DIR / "fast_index_artifacts.json").read_text())
# These discovered LANG tables are the language dispatch used by extract_file.
DISPATCH_PIN = [
    "bash",
    "c",
    "cpp",
    "csharp",
    "dart",
    "elixir",
    "go",
    "haskell",
    "java",
    "javascript",
    "kotlin",
    "lua",
    "php",
    "python",
    "ruby",
    "rust",
    "scala",
    "solidity",
    "swift",
    "tsx",
    "typescript",
]


class CountingProvider:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def extract(self, path: Path, source: str, language: str):
        self.paths.append(path)
        return extract_file(str(path), source, language)


def _schema(db_path: Path) -> dict[str, list[str]]:
    with sqlite3.connect(db_path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return {
            name: [
                row[1] for row in connection.execute(f'PRAGMA table_xinfo("{name}")')
            ]
            for (name,) in tables
        }


def _assert_schema(
    actual: dict[str, list[str]], expected: dict[str, list[str]]
) -> None:
    assert actual == expected


def _fast_source_digest(root: Path) -> str:
    tracked_paths = subprocess.check_output(
        [  # noqa: S607 - Runs the test's locally built helper executable.
            "git",
            "ls-files",
            "--",
            "code/src/varde_code/index",
            "code/src/varde_code/extract",
            "code/src/varde_code/complexity.py",
            "code/src/varde_code/parse.py",
        ],
        cwd=root,
        text=True,
    )
    digest = hashlib.sha256()
    for relative_path in tracked_paths.splitlines():
        digest.update(relative_path.encode() + b"\0")
        digest.update((root / relative_path).read_bytes() + b"\0")
    return digest.hexdigest()


def _write_fixture(root: Path) -> None:
    root.mkdir()
    (root / "alpha.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (root / "beta.ts").write_text("function beta() { return 2; }\n", encoding="utf-8")
    (root / "gamma.py").write_text("value = 3\n", encoding="utf-8")


def _file_snapshot(roots: list[Path]) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_built_index_matches_pinned_schema(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _write_fixture(root)
    config = tmp_path / "config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))

    built = build(root, CountingProvider())

    actual_schema = _schema(Path(built.db_path))
    _assert_schema(actual_schema, SCHEMA_PIN)


def test_extract_file_dispatch_matches_pinned_languages():
    dispatch = sorted(language_tables())
    assert dispatch == DISPATCH_PIN, (
        "extract_file dispatch changed: "
        f"missing={sorted(set(DISPATCH_PIN) - set(dispatch))}, "
        f"added={sorted(set(dispatch) - set(DISPATCH_PIN))}"
    )


# D28 evidence for the lexical-index pin update (code-lexical-rank): full build
# +8.9% (114.8s -> 124.9s), one-file refresh 4.59s -> 4.25s, unchanged refresh
# 0.061s -> 0.050s, schema_version 19 -> 20 (adds the five lexical* tables).
# D28 evidence for discovery pruning (plan-gate-map-build-slow): the real
# checkout's fresh /tmp-index build completed in 261.54s for 3,762 files
# (687,194 entities, 547,842 symbols), within the 300s bound and without schema
# changes.
# D28 evidence for index provenance (index-staleness-signal). Command: copy
# code/src (505 files) to a fresh git repo, then in one process with a fresh
# VARDE_CONFIG_DIR time `index.build.build(root, extractor)` and then
# `index.incremental.refresh(root, extractor)` with time.time(), via
# `uv run python bench.py <repo> base|new <config-dir>`; "base" stubs
# `record_built` and `refresh_provenance_if_due` to no-ops. Three runs each:
# full build 8.7-9.0s base vs 8.6-9.0s new (noise); unchanged refresh
# 0.007s base vs 0.024-0.025s new (one `git rev-parse HEAD`, plus one when
# deciding the non-git age limit); no schema change. User approved the re-pin
# (2026-10-30).
# D28 evidence for pruning root docs/repo-map (pack-write-idempotent): same copy
# (348 files), bench alternating base (prune stubbed off) and new, 3 runs each:
# full build 8.84-8.88s base vs 8.86-8.96s new; unchanged refresh 0.024-0.025s
# both; discovery walk 3.3-3.4ms both; no schema change. Re-pin per coordinator.
# D28 evidence for the flow-role cache (flow-role-cache). Command: throwaway
# VARDE_CONFIG_DIR, `uv run varde map build --repo-root <repo> --force` on the
# real checkout. Full build min 96s before (runs 97, 96) vs 69s after (runs 69,
# 79, 82, 71); no schema change.
# Approval: user replied "Recommendations are good" (2026-10-30) to "approve
# re-pinning the fast-index digest for the plan's speed changes? 1 whole plan
# (recommended)". Plan criterion t1 (>= 30s) was met as intent only (27s saved
# against a 96s measured baseline, not 142s).
# D28 evidence for gitignore discovery (gitignore-discovery). Command: throwaway
# VARDE_CONFIG_DIR, `uv run varde map build --repo-root <real checkout> --force`
# with worktree source. Full build 69s before (runs 69, 69) vs 66s after (runs
# 66, 66); files 5472 -> 4869 (gitignored .svelte-kit and tree-sitter-cache rows
# dropped); no schema change. Same approval as above; plan criterion t2 (>= 10s)
# was met as intent only (3s saved).
# D28 evidence for parallel extraction (parallel-extraction-spike). Command:
# throwaway VARDE_CONFIG_DIR, `uv run varde map build --repo-root <real checkout>
# --force` with worktree source, 8 spawn workers. Extraction phase 54.7s, 54.9s
# serial vs 14.7s, 15.0s parallel; full build 66s, 66s vs 28s, 28s; tree peak RSS
# 1.83 GB vs 2.34 GB (1.26x); canonical index diff (files, entities, edges,
# metrics, symbols, diagnostics, communities) empty; no schema change. Same
# approval as above. Review-fix re-pin (2026-10-30): cancel_futures on interrupt,
# process_cpu_count, non-UTF-8 git names kept via os.fsdecode, lstat diagnostics
# in git mode; extraction logic unchanged, so the timings above still apply.
# Re-pin (memory-default plan): fnv1a64 moved to varde_core.paths; behavior
# unchanged (pure move). repo_db_path is pinned by test_index_paths. The main
# agent approved this re-pin as a pure move.
def test_fast_index_sources_match_pinned_digest():
    expected_digest = (GUARD_DIR / "fast_path_source_digest.txt").read_text().strip()
    assert _fast_source_digest(Path(__file__).parents[4]) == expected_digest, (
        "Fast-index source changed; intentional changes require D28 measurement "
        "and approval before updating this pin."
    )


def test_build_extracts_each_fixture_source_once(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _write_fixture(root)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    provider = CountingProvider()

    build(root, provider)

    assert len(provider.paths) == 3


def test_build_and_refresh_create_only_pinned_index_artifacts(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    config = tmp_path / "config"
    data = tmp_path / "data"
    _write_fixture(root)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    assert _file_snapshot([config, data]) == {}

    built = build(root, CountingProvider())
    db_path = Path(built.db_path)
    index_dir = db_path.parent
    artifacts_after_build = sorted(path.name for path in index_dir.iterdir())
    assert artifacts_after_build == ARTIFACT_PIN
    config_after_build = _file_snapshot([config])
    data_after_build = _file_snapshot([data])
    assert data_after_build == {}
    assert all(
        Path(relative).is_relative_to(index_dir.relative_to(config))
        for relative in config_after_build
    )

    refresh(root, CountingProvider())

    assert sorted(path.name for path in index_dir.iterdir()) == ARTIFACT_PIN
    assert _file_snapshot([config]) == config_after_build
    assert _file_snapshot([data]) == data_after_build


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE files ADD COLUMN unexpected_column TEXT",
        "CREATE TABLE unexpected_table (id INTEGER PRIMARY KEY)",
    ],
)
def test_schema_guard_rejects_real_database_changes(tmp_path, monkeypatch, mutation):
    root = tmp_path / "repo"
    _write_fixture(root)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    built = build(root, CountingProvider())
    database = Path(built.db_path)

    with sqlite3.connect(database) as connection:
        connection.execute(mutation)

    with pytest.raises(AssertionError):
        _assert_schema(_schema(database), SCHEMA_PIN)


def test_no_change_refresh_does_not_extract_write_or_create_quality_store(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    _write_fixture(root)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    initial_provider = CountingProvider()
    built = build(root, initial_provider)
    refresh(root, initial_provider)  # Persist hashes before checking the warm path.
    db_path = Path(built.db_path)
    before_files = sorted(path.name for path in db_path.parent.iterdir())
    before_db = db_path.read_bytes()
    before_sidecars = {
        path.name: path.read_bytes()
        for path in db_path.parent.glob(f"{db_path.name}-*")
        if path.is_file()
    }
    provider = CountingProvider()

    summary = refresh(root, provider)

    assert provider.paths == []
    assert summary.changed_files == ()
    assert summary.unchanged == 3
    assert summary.reparsed == 0
    assert db_path.read_bytes() == before_db
    assert {
        path.name: path.read_bytes()
        for path in db_path.parent.glob(f"{db_path.name}-*")
        if path.is_file()
    } == before_sidecars
    assert sorted(path.name for path in db_path.parent.iterdir()) == before_files
    assert "index.db" in before_files
    assert not any("quality" in name.lower() for name in before_files)
    assert _schema(Path(summary.db_path)) == SCHEMA_PIN


def test_fast_entry_point_imports_do_not_load_quality_modules(tmp_path):
    script = """
import importlib, sys
for name in (
    'varde_code.index', 'varde_code.index.build', 'varde_code.index.incremental',
    'varde_code.module', 'varde_code.cli_index', 'varde_code.cli_query',
    'varde_code.cli_edit',
):
    importlib.import_module(name)
importlib.import_module('varde_code.module').register()
offenders = sorted(
    name for name in sys.modules if name.startswith('varde_code.quality_')
)
assert not offenders, f'Unexpected quality modules imported: {offenders}'
"""
    env = os.environ.copy()
    for name in ("HOME", "XDG_CONFIG_HOME", "VARDE_CONFIG_DIR", "XDG_DATA_HOME"):
        path = tmp_path / name
        path.mkdir()
        env[name] = str(path)
    result = subprocess.run(  # noqa: S603 - Runs a controlled CLI fixture to verify fast-index guards.
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[4],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stderr}\n{result.stdout}"
