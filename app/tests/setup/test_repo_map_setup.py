from pathlib import Path

import pytest
from varde.setup.sync import support
from varde.setup.sync.command import run

BLOCK_START = "<!-- varde-map:start -->"


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def fake_build(root: Path) -> None:
        calls.append(root)
        (root / "docs" / "repo-map").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "repo-map" / "README.md").write_text("map")

    monkeypatch.setattr(support, "_build_packs", fake_build)
    monkeypatch.setattr(support, "_tracked_files", lambda _root: ["src/a.py"])
    return calls


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    *flags: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.chdir(repo)
    args = ["--skills-dir", str(tmp_path / "s"), "--agents-dir", str(tmp_path / "a")]
    base = [*args, "--harnesses", "none", "--skills", "varde-build"]
    assert run([*base, *flags]) == 0


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_yes_writes_block_modules_and_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builds: list[Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    _setup(tmp_path, monkeypatch, repo, "--yes")

    out = capsys.readouterr().out
    assert BLOCK_START in (repo / "AGENTS.md").read_text()
    assert (repo / "docs/repo-map/README.md").exists()
    assert (repo / "docs/repo-map/modules.txt").read_text() == "src\n"
    assert builds == [repo]
    assert "varde map packs status --check" in out
    assert "build --stale" in out
    assert "sandbox" in out


@pytest.mark.parametrize("flag", ["--no-packs", "--dry-run", "--json"])
def test_flags_write_and_build_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builds: list[Path],
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    repo = _repo(tmp_path)
    _setup(tmp_path, monkeypatch, repo, flag)

    out = capsys.readouterr().out
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / "docs").exists()
    assert builds == []
    assert ("would edit AGENTS.md" in out) == (flag == "--dry-run")


def test_tty_answer_n_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builds: list[Path]
) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(support.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    _setup(tmp_path, monkeypatch, repo)

    assert not (repo / "AGENTS.md").exists()
    assert builds == []


def test_linked_worktree_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builds: list[Path]
) -> None:
    repo = tmp_path / "linked"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: elsewhere\n")
    _setup(tmp_path, monkeypatch, repo, "--yes")

    assert not (repo / "AGENTS.md").exists()
    assert builds == []
