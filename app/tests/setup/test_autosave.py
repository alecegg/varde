from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from varde.setup.autosave import _parse_batch, _parse_raw, run


def git(path: Path, *args: str, input: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(path), *args], input=input, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def store(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "store"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
    )
    git(repo, "config", "user.name", "Autosave Test")
    git(repo, "config", "user.email", "autosave@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "initial.txt").write_text("initial\n")
    git(repo, "add", "initial.txt")
    git(repo, "commit", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "--set-upstream", "origin", "main")
    return repo, remote


def invoke(*args: str) -> int:
    return run(list(args), None)


# Kept despite using private helpers: git never emits a malformed raw diff or a
# non-blob batch record, so no public path reaches these branches. Listed in
# plans/2026-10-17-test-quality-sweep/notes/g2-internals.md.
def test_parse_raw_detects_missing_path() -> None:
    with pytest.raises(RuntimeError, match="malformed git raw diff"):
        _parse_raw(b":100644 100644 abc def M")


def test_parse_raw_detects_bad_header() -> None:
    with pytest.raises(RuntimeError, match="malformed git raw diff header"):
        _parse_raw(b":100644 M\0file\0")


def test_parse_batch_rejects_missing_header_newline() -> None:
    with pytest.raises(RuntimeError, match="batch header"):
        _parse_batch(b"abc blob 0")


def test_parse_batch_rejects_non_blob() -> None:
    with pytest.raises(RuntimeError, match="non-blob"):
        _parse_batch(b"abc tree 0\n\n")


def test_parse_batch_rejects_truncated_body() -> None:
    with pytest.raises(RuntimeError, match="batch body"):
        _parse_batch(b"abc blob 2\na\n")


def test_run_commits_files_whose_names_need_raw_path_bytes(tmp_path: Path) -> None:
    repo, _ = store(tmp_path)
    (repo / "a file.txt").write_text("spaces\n")
    (repo / "a\nfile.txt").write_text("newline\n")
    assert invoke("run", "--repo", str(repo)) == 0
    committed = git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD").split(b"\0")
    assert {name for name in committed if name} == {
        b"a file.txt",
        b"a\nfile.txt",
        b"initial.txt",
    }


def test_scan_only_reports_secrets_behind_empty_and_nul_bodies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = store(tmp_path)
    git(repo, "checkout", "-b", "mixed")
    git(repo, "branch", "--set-upstream-to=origin/main", "mixed")
    key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
    (repo / "empty.txt").write_bytes(b"")
    (repo / "binary.bin").write_bytes(b"\0" + key.encode())
    (repo / "secret.txt").write_text(key)
    git(repo, "add", "empty.txt", "binary.bin", "secret.txt")
    git(repo, "commit", "-m", "mixed blobs")
    assert invoke("run", "--repo", str(repo), "--branch", "mixed", "--scan-only") == 1
    error = capsys.readouterr().err
    assert "secret detected in 'binary.bin'" in error
    assert "secret detected in 'secret.txt'" in error
    assert "not pushing" in error


def test_help_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert invoke("--help") == 0
    assert "Schedule commits" in capsys.readouterr().out


@pytest.mark.parametrize("interval", ["0", "-1"])
def test_install_rejects_nonpositive_interval(
    tmp_path: Path, interval: str, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = store(tmp_path)
    assert (
        invoke(
            "install", "--repo", str(repo), "--interval-minutes", interval, "--dry-run"
        )
        != 0
    )
    assert "interval-minutes" in capsys.readouterr().err


def test_run_requires_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert invoke("run") != 0
    assert "--repo" in capsys.readouterr().err


def test_rejects_non_git_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert invoke("run", "--repo", str(tmp_path)) == 1
    assert "not a git repo" in capsys.readouterr().err


def test_rejects_nested_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = tmp_path / "code"
    code.mkdir()
    subprocess.run(["git", "init", str(code)], check=True, capture_output=True)
    nested = code / "nested"
    nested.mkdir()
    assert invoke("run", "--repo", str(nested)) == 1
    assert "inside a code repo" in capsys.readouterr().err


def test_run_commits_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, remote = store(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (repo / "initial.txt").write_text("changed\n")
    (repo / "new.txt").write_text("new\n")
    assert invoke("run", "--repo", str(repo)) == 0
    assert git(repo, "rev-parse", "HEAD") == git(remote, "rev-parse", "refs/heads/main")
    assert git(repo, "log", "-1", "--format=%s").decode().startswith("autosave ")


def test_run_skips_ignored_file(tmp_path: Path) -> None:
    repo, _ = store(tmp_path)
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "ignored").mkdir()
    (repo / "ignored/file.txt").write_text("ignored")
    assert invoke("run", "--repo", str(repo)) == 0
    assert git(repo, "status", "--porcelain") == b""


def test_run_skips_oversized_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = store(tmp_path)
    (repo / "large.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    (repo / "small.txt").write_text("small")
    assert invoke("run", "--repo", str(repo), "--max-file-mb", "1") == 0
    assert "oversized file" in capsys.readouterr().err
    assert b"large.bin" not in git(repo, "show", "--format=", "--name-only", "HEAD")


def test_run_does_not_commit_when_no_changes(tmp_path: Path) -> None:
    repo, _ = store(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    assert invoke("run", "--repo", str(repo)) == 0
    assert git(repo, "rev-parse", "HEAD") == before


def test_run_requires_upstream(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    assert invoke("run", "--repo", str(repo)) == 1
    assert "no upstream configured" in capsys.readouterr().err


def test_scan_only_blocks_secret_and_does_not_commit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = store(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "secret-branch")
    git(repo, "branch", "--set-upstream-to=origin/main", "secret-branch")
    (repo / "secret.txt").write_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
    )
    git(repo, "add", "secret.txt")
    git(repo, "commit", "-m", "secret")
    assert (
        invoke("run", "--repo", str(repo), "--branch", "secret-branch", "--scan-only")
        == 1
    )
    output = capsys.readouterr().err
    assert "secret detected" in output
    assert "not pushing" in output
    assert git(repo, "rev-parse", "HEAD") != before


def test_scan_only_allows_ordinary_dotenv_value(tmp_path: Path) -> None:
    repo, _ = store(tmp_path)
    git(repo, "checkout", "-b", "dotenv")
    git(repo, "branch", "--set-upstream-to=origin/main", "dotenv")
    (repo / ".env").write_text("NAME=ordinary-value\n")
    git(repo, "add", ".env")
    git(repo, "commit", "-m", "dotenv")
    assert invoke("run", "--repo", str(repo), "--branch", "dotenv", "--scan-only") == 0


def test_install_dry_run_prints_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = store(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert invoke("install", "--repo", str(repo), "--dry-run") == 0
    output = capsys.readouterr().out
    assert "<key>StartInterval</key><integer>1800</integer>" in output
    assert "launchctl bootstrap gui/" in output


def test_install_escapes_xml_and_uses_custom_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "a&b"
    root.mkdir()
    repo, _ = store(root)
    git(repo, "checkout", "-b", "nightly")
    git(repo, "branch", "--set-upstream-to=origin/main", "nightly")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert (
        invoke(
            "install",
            "--repo",
            str(repo),
            "--branch",
            "nightly",
            "--interval-minutes",
            "5",
            "--max-file-mb",
            "3",
            "--dry-run",
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "nightly" in output
    assert "a&amp;b" in output
    assert "<integer>300</integer>" in output
    assert "<string>3</string>" in output


def test_install_and_uninstall_use_stubbed_launchctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = store(tmp_path)
    root = tmp_path / "home"
    plist_dir = root / "launchagents"
    fake = tmp_path / "launchctl"
    log = tmp_path / "launchctl.log"
    fake.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$VARDE_AUTOSAVE_TEST_LAUNCHCTL_LOG"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("VARDE_AUTOSAVE_TEST_PLIST_DIR", str(plist_dir))
    monkeypatch.setenv("VARDE_AUTOSAVE_TEST_LAUNCHCTL", str(fake))
    monkeypatch.setenv("VARDE_AUTOSAVE_TEST_LAUNCHCTL_LOG", str(log))
    assert invoke("install", "--repo", str(repo)) == 0
    plist = next(plist_dir.glob("*.plist"))
    assert plist.exists()
    assert invoke("uninstall", "--repo", str(repo)) == 0
    assert not plist.exists()
    assert log.read_text().count("gui/") == 2


@pytest.mark.parametrize("branch", ["main", "other", "detached"])
def test_run_tick_guards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], branch: str
) -> None:
    repo, _ = store(tmp_path)
    if branch == "other":
        git(repo, "checkout", "-b", "other")
        git(repo, "branch", "--set-upstream-to=origin/main", "other")
    elif branch == "detached":
        git(repo, "checkout", "--detach")
    assert invoke("run", "--repo", str(repo), "--branch", "main") == 0
    if branch != "main":
        assert "skipping tick" in capsys.readouterr().err
