import json
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from varde_code.module import register
from varde_code.quality_score.cli.baseline import run

SIMPLE = "def add(a, b):\n    return a + b\n"


class _IO:
    def __init__(self) -> None:
        self.stdout = StringIO()
        self.stderr = StringIO()


def git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text(SIMPLE, encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_build_writes_the_output_path_and_show_reads_it(repo: Path) -> None:
    output = repo / "out" / "ref.json"
    io = _IO()
    code = run(
        ["quality", "reference", "build", "--root", str(repo), "--output", str(output)],
        io,
    )
    assert code == 0, io.stderr.getvalue()
    assert json.loads(output.read_text(encoding="utf-8"))["n"] == 2
    shown = _IO()
    code = run(
        [
            "quality",
            "reference",
            "show",
            "--root",
            str(repo),
            "--reference",
            str(output),
        ],
        shown,
    )
    assert code == 0
    view = json.loads(shown.stdout.getvalue())
    assert view["n"] == 2
    assert view["built"] == "command"
    assert "p10" in view


def test_show_without_a_stored_reference_builds_an_auto_one(repo: Path) -> None:
    io = _IO()
    assert run(["quality", "reference", "show", "--root", str(repo)], io) == 0
    assert json.loads(io.stdout.getvalue())["built"] == "auto"


def test_empty_repo_exits_2_with_message(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    io = _IO()
    assert run(["quality", "reference", "build", "--root", str(tmp_path)], io) == 2
    assert "no scorable python source" in io.stderr.getvalue()


def test_build_help_names_the_output_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["quality", "reference", "build", "--help"])
    assert exit_info.value.code == 0
    assert "--output" in capsys.readouterr().out


def test_module_router_reaches_reference() -> None:
    io = _IO()
    with pytest.raises(SystemExit) as exit_info:
        register().run(["quality", "reference", "build", "--help"], io)
    assert exit_info.value.code == 0
