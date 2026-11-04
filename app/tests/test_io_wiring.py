"""The app capability set wires the workflow independence check end to end."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from varde import cli
from varde.io import create_io
from varde_code.index.paths import repo_db_path
from varde_workflow import cli as workflow_cli


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    plan = root / "plan"
    (plan / "tasks").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "seed.rs").touch()
    (root / "src" / "a.py").write_text("def a():\n    return 1\n")
    (root / "src" / "b.py").write_text("def b():\n    return 2\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root, plan


def _creates(plan: Path, name: str, path: str) -> None:
    (plan / "tasks" / f"{name}.md").write_text(
        f"---\ntype: task\nstatus: todo\ndepends_on: []\ncreates: [{path}]\n---\n"
    )


def _owns(plan: Path, name: str, path: str) -> None:
    (plan / "tasks" / f"{name}.md").write_text(
        f"---\ntype: task\nstatus: todo\ndepends_on: []\nowns: [{path}]\n---\n"
    )


def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))


def _wave_via_cli(root: Path, plan: Path, capsys: pytest.CaptureFixture[str]) -> dict:
    status = cli.main(
        [
            "plan",
            "execution-wave",
            str(plan),
            "--repo-root",
            str(root),
            "--max-workers",
            "3",
            "--json",
        ]
    )
    assert status == 0
    return json.loads(capsys.readouterr().out)["data"]


def _failed_queries(data: dict) -> list[str]:
    return [reason for reason in data["reasons"] if "blast_radius failed" in reason]


def test_create_io_provides_code_impact() -> None:
    assert create_io().impact is not None


def test_execution_wave_parallelizes_disjoint_creates_through_app_io(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, plan = _repo(tmp_path)
    _creates(plan, "alpha", "src/new-a.rs")
    _creates(plan, "beta", "src/new-b.rs")

    status = workflow_cli.run(
        [
            "plan",
            "execution-wave",
            str(plan),
            "--repo-root",
            str(root),
            "--max-workers",
            "3",
            "--json",
        ],
        create_io(),
    )

    assert status == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["next_wave"] == ["alpha", "beta"]
    assert data["conflicts"] == []


def test_execution_wave_parallelizes_disjoint_existing_owners_through_real_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, plan = _repo(tmp_path)
    _owns(plan, "alpha", "src/a.py")
    _owns(plan, "beta", "src/b.py")
    _isolated_config(tmp_path, monkeypatch)
    assert cli.main(["map", "build", "--repo-root", str(root)]) == 0
    capsys.readouterr()

    data = _wave_via_cli(root, plan, capsys)

    assert data["next_wave"] == ["alpha", "beta"]
    assert data["conflicts"] == []
    assert _failed_queries(data) == []


def test_execution_wave_serializes_overlapping_existing_ownership_through_real_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, plan = _repo(tmp_path)
    _owns(plan, "alpha", "src/a.py")
    _owns(plan, "beta", "src/a.py")
    _isolated_config(tmp_path, monkeypatch)
    assert cli.main(["map", "build", "--repo-root", str(root)]) == 0
    capsys.readouterr()

    data = _wave_via_cli(root, plan, capsys)

    assert data["next_wave"] == ["alpha"]
    assert data["conflicts"] == [{"tasks": ["alpha", "beta"], "files": ["src/a.py"]}]
    assert _failed_queries(data) == []


def test_execution_wave_never_builds_a_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, plan = _repo(tmp_path)
    _owns(plan, "alpha", "src/a.py")
    _isolated_config(tmp_path, monkeypatch)
    index = repo_db_path(root)
    assert not index.exists()

    data = _wave_via_cli(root, plan, capsys)

    assert not index.exists()
    assert _failed_queries(data) != []
