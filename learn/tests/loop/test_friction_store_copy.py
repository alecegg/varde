from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
VERIFY = TESTS / "verify_friction_store.py"
GOLDEN = TESTS / "golden" / "friction"
LEDGER = TESTS.parents[2] / "data" / "tests" / "fixtures" / "ledger"


def _run_verifier(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - checked-in verifier under this interpreter.
        [sys.executable, str(VERIFY), str(store), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_golden_store_copy_verifies(tmp_path: Path) -> None:
    store = tmp_path / "golden-store"
    store.mkdir()
    shutil.copyfile(GOLDEN / "friction.jsonl", store / "friction.jsonl")

    result = _run_verifier(store, "--golden-dump", str(GOLDEN / "learn.db.json"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS friction store verification" in result.stdout


def test_configured_real_store_copy_verifies() -> None:
    configured = os.environ.get("VARDE_FRICTION_STORE")
    if not configured:
        pytest.skip("set VARDE_FRICTION_STORE to run the copied real-store gate")
    source = Path(configured).expanduser()
    if not source.is_dir():
        pytest.skip(f"configured friction store is absent: {source}")

    result = _run_verifier(source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS friction store verification" in result.stdout


def test_golden_store_copy_verifies_ledger_and_digests(tmp_path: Path) -> None:
    store = tmp_path / "ledger-store"
    shutil.copytree(LEDGER, store)
    shutil.copyfile(GOLDEN / "friction.jsonl", store / "friction.jsonl")

    result = _run_verifier(store, "--golden-dump", str(GOLDEN / "learn.db.json"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS analyzed ledger and digests" in result.stdout
