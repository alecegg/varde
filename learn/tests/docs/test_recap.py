import json
import shutil
import subprocess
from pathlib import Path

import pytest
from varde_learn.docs.cli import run
from varde_learn.docs.recap.build import Caps, build_recap
from varde_learn.docs.recap.gitdiff import GitError, changed_files
from varde_learn.docs.recap.owns import matches
from varde_learn.docs.recap.plan import read_plan

GIT = shutil.which("git") or "git"
FIXTURE = Path(__file__).parent / "fixtures" / "recap"


def git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        [GIT, "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def write(root: Path, name: str, text: str | bytes) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, "src/api/old.py", "a\nb\nc\nd\ne\nf\n")
    write(root, "src/api/gone.py", "x\n")
    write(root, "src/model.py", "m\n")
    write(root, "lib/util.py", "u\n")
    write(root, "lib2/other.py", "o\n")
    write(root, "bin.dat", b"\x00\x01\x02")
    write(root, "docs/shared.md", "s\n")
    write(root, "tests/unit/deep/test_a.py", "t\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


@pytest.fixture
def plan_file(tmp_path: Path) -> Path:
    dest = tmp_path / "plans" / "demo"
    shutil.copytree(FIXTURE, dest)
    return dest / "plan.md"


def recap(repo: Path, plan_file: Path, caps: Caps | None = None) -> dict:
    plan = read_plan(plan_file)
    return build_recap(
        plan, changed_files(repo, "HEAD~1", "HEAD"), "HEAD~1", "HEAD", "demo", caps
    )


def commit_changes(repo: Path) -> None:
    write(repo, "src/api/old.py", "a\nB\nc\nd\ne\nf\nnew1\nnew2\n")
    (repo / "src/api/gone.py").unlink()
    write(repo, "src/model.py", "m\nm2\n")
    write(repo, "lib2/other.py", "o2\n")  # prefix-vs-glob: "lib" must not own lib2
    write(repo, "bin.dat", b"\x00\x05\x06\x07")
    write(repo, "docs/shared.md", "s2\n")
    write(repo, "sub/CHANGELOG.md", "c\n")
    write(repo, "tests/unit/deep/test_a.py", "t2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "work")


def rows(result: dict) -> dict:
    return {r["file"]: r for r in result["rows"]}


def test_mapping_and_drift(repo: Path, plan_file: Path) -> None:
    commit_changes(repo)
    result = recap(repo, plan_file)
    by_file = rows(result)
    assert by_file["src/api/old.py"]["tasks"] == ["t1-api"]
    assert by_file["src/api/old.py"]["blocks"] == ["order-flow"]
    assert by_file["src/api/old.py"]["added"] == [[2, 2], [7, 8]]
    assert by_file["src/api/old.py"]["removed"] == [[2, 2]]
    assert by_file["src/model.py"]["blocks"] == ["order-model"]
    assert by_file["tests/unit/deep/test_a.py"]["tasks"] == [
        "t1-api"
    ]  # ** crosses dirs
    assert by_file["lib2/other.py"]["drift"] == [
        "unplanned"
    ]  # bare "lib" is not "lib2"
    assert by_file["docs/shared.md"]["shared"] is True
    assert by_file["docs/shared.md"]["drift"] == []
    assert by_file["sub/CHANGELOG.md"]["shared"] is True  # shared glob with **
    assert {"owns": "src/never/", "task": "t1-api"} in result["untouched"]
    assert {"owns": "lib", "task": "t1-api"} in result["untouched"]
    assert result["unverified"] == ["lonely"]
    assert result["summary"]["unplanned"] == 2  # lib2/other.py and bin.dat


def test_delete_and_binary(repo: Path, plan_file: Path) -> None:
    commit_changes(repo)
    by_file = rows(recap(repo, plan_file))
    assert by_file["src/api/gone.py"]["status"] == "D"
    assert by_file["src/api/gone.py"]["removed"] == [[1, 1]]
    assert by_file["src/api/gone.py"]["tasks"] == ["t1-api"]
    binary = by_file["bin.dat"]
    assert binary["binary"] is True
    assert binary["hunk"] == "" and binary["added"] == []


def test_rename_maps_both_paths(repo: Path, plan_file: Path) -> None:
    (repo / "elsewhere").mkdir()
    git(repo, "mv", "src/api/old.py", "elsewhere/renamed.py")
    git(repo, "commit", "-qm", "rename")
    by_file = rows(recap(repo, plan_file))
    row = by_file["elsewhere/renamed.py"]
    assert row["status"] == "R" and row["old_file"] == "src/api/old.py"
    assert row["tasks"] == ["t1-api"]  # owned through the old path
    assert row["drift"] == []


def test_size_cap(repo: Path, plan_file: Path) -> None:
    commit_changes(repo)
    big = "\n".join(f"line {i}" for i in range(500))
    write(repo, "src/api/big.py", big)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "big")
    plan = read_plan(plan_file)
    changes = changed_files(repo, "HEAD~1", "HEAD")
    result = build_recap(
        plan, changes, "HEAD~1", "HEAD", "demo", Caps(per_file=100, total=1000)
    )
    row = rows(result)["src/api/big.py"]
    assert row["truncated"] is True
    assert len(row["hunk"].encode()) <= 100
    assert row["added"] == [[1, 500]]  # ranges are never capped


def test_identical_bytes_on_rerun(
    repo: Path,
    plan_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    commit_changes(repo)
    monkeypatch.chdir(repo)
    argv = ["doc", "recap", str(plan_file), "--base", "HEAD~1", "--json"]
    assert run(argv) == 0
    first = capfd.readouterr().out
    assert run(argv) == 0
    assert capfd.readouterr().out == first
    assert json.loads(first)["summary"]["files"] == 8


def test_cli_errors(
    repo: Path,
    plan_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repo)
    assert run(["doc", "recap", str(plan_file)]) == 2
    assert "--base" in capfd.readouterr().err
    assert run(["doc", "recap", str(plan_file), "--base", "nope"]) == 1
    assert run(["doc", "recap", str(plan_file), "--base", "--evil"]) in {1, 2}


@pytest.mark.parametrize(
    ("entry", "path", "expected"),
    [
        ("src/api/", "src/api/a/b.py", True),
        ("src/api", "src/api/a.py", True),
        ("src/api", "src/apix/a.py", False),
        ("src/api", "src/api", True),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("src/**/*.py", "src/a.py", True),
        ("src/**/*.py", "src/x/y/a.py", True),
        ("src/**", "src/x/y", True),
        ("a?.py", "ab.py", True),
        ("a?.py", "a/.py", False),
    ],
)
def test_matcher_pins(entry: str, path: str, expected: bool) -> None:
    assert matches(entry, path) is expected


def test_paths_with_spaces_and_quotes_keep_their_ranges(repo: Path) -> None:
    names = ["my file.txt", 'q"x.txt', "tab\there.txt"]
    for name in names:
        write(repo, name, "a\nb\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "odd names")
    for name in names:
        write(repo, name, "a\nB\nc\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "edit odd names")
    by_path = {c.path: c for c in changed_files(repo, "HEAD~1", "HEAD")}
    for name in names:
        assert by_path[name].added == [[2, 3]]
        assert by_path[name].removed == [[2, 2]]
        assert by_path[name].hunk_lines


@pytest.mark.parametrize("ref", ["", "-x", "no-such-ref", "src/model.py"])
def test_invalid_refs_are_refused_not_read_as_pathspecs(repo: Path, ref: str) -> None:
    write(repo, "src/model.py", "m\nm2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "next")
    with pytest.raises(GitError):
        changed_files(repo, "HEAD~1", ref)
    with pytest.raises(GitError):
        changed_files(repo, ref, "HEAD")
