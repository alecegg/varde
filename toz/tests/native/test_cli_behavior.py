from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).parents[2]


def run_cli(
    tmp_path: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    config = tmp_path / "config"
    store = tmp_path / "store"
    for path in (home, config, store):
        path.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_TOZ_CONFIG_DIR": str(store),
            "PYTHONPATH": str(PACKAGE / "src"),
        }
    )
    return subprocess.run(  # noqa: S603 - Test invokes the current Python interpreter with fixed module argv.
        [sys.executable, "-m", "varde_toz.cli", *args],
        cwd=tmp_path,
        env=env,
        input=input,
        text=True,
        capture_output=True,
        check=False,
    )


def test_run_script_prints_each_line(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "run", "--code", "print('a'); print('b')")
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["a", "b"]


def test_large_script_output_can_be_queried_by_handle(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "run",
        "--code",
        (
            "const r=toz.exec({argv:['sh','-c','yes x | head -c 70000']}); "
            "print(r.capture.handle);"
        ),
    )
    assert result.returncode == 0
    handle = result.stdout.strip()
    queried = run_cli(tmp_path, "query", "--handle", handle)
    assert queried.returncode == 0
    assert queried.stdout.startswith("x\n" * 100)


def test_indexed_file_search_returns_match_and_empty_search_succeeds(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("amber marker in first file\n")
    second.write_text("blue marker in second file\n")
    first_index = run_cli(tmp_path, "index", str(first), "--label", "first-file")
    second_index = run_cli(tmp_path, "index", str(second), "--label", "second-file")
    assert first_index.returncode == second_index.returncode == 0

    found = run_cli(tmp_path, "query", "amber", "--json")
    assert found.returncode == 0
    hits = json.loads(found.stdout)[0]["hits"]
    assert len(hits) == 1
    assert hits[0]["label"] == "first-file"

    absent = run_cli(tmp_path, "query", "missing-marker", "--json")
    assert absent.returncode == 0
    assert json.loads(absent.stdout)[0]["hits"] == []


def test_capture_redacts_secret_from_stored_query_text(tmp_path: Path) -> None:
    token = "ghp_" + "a" * 36
    captured = run_cli(
        tmp_path,
        "capture",
        "--force",
        "--source",
        "fixture",
        input=f"output {token}\n" * 1000,
    )
    assert captured.returncode == 0
    match = re.search(r"handle\s+(\w+)", captured.stdout)
    assert match, captured.stdout
    handle = match.group(1)

    queried = run_cli(tmp_path, "query", "--handle", handle)
    assert queried.returncode == 0
    assert token not in queried.stdout
    assert "[redacted:github]" in queried.stdout
