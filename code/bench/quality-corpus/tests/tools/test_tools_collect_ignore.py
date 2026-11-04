"""Golden corpus files stay out of pytest collection from supported roots."""

import os
import subprocess
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[2]
REPO = CORPUS.parents[2]


def collect(cwd: Path, import_mode: str | None = None) -> list[str]:
    args = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if import_mode is not None:
        args.append(f"--import-mode={import_mode}")
    args.append(str(CORPUS) if cwd == REPO else ".")
    result = subprocess.run(  # noqa: S603 - Runs the ignore collector CLI against a temporary fixture.
        args,
        check=False,
        capture_output=True,
        cwd=cwd,
        env=os.environ.copy(),
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    ids = [line for line in result.stdout.splitlines() if "::" in line]
    assert ids
    assert any("tests/" in test_id for test_id in ids)
    assert not any(
        test_id.startswith("items/") or "quality-corpus/items/" in test_id
        for test_id in ids
    )
    return ids


def test_collection_ignores_items_from_repository_root() -> None:
    collect(REPO)


def test_collection_ignores_items_from_corpus_directory() -> None:
    collect(CORPUS)


def test_collection_ignores_items_with_importlib_mode() -> None:
    collect(REPO, "importlib")
