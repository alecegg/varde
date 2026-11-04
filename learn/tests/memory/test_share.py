# ruff: noqa: S603, S607
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
from varde_learn.loop import cli_memory, cli_memory_surface
from varde_learn.memory import share, store
from varde_learn.memory.entry import Entry

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Alice",
    "GIT_AUTHOR_EMAIL": "a@example.invalid",
    "GIT_COMMITTER_NAME": "Alice",
    "GIT_COMMITTER_EMAIL": "a@example.invalid",
}


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def remote(tmp_path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", str(bare), str(seed)], check=True, capture_output=True
    )
    git(seed, "checkout", "-b", "main")
    (seed / "README.md").write_text("shared memory\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "init")
    git(seed, "push", "origin", "main")
    return bare


@pytest.fixture
def user(tmp_path, monkeypatch, remote):
    """`use(name)` switches to that user's memory root, config and data dir."""

    def use(name: str) -> Path:
        monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / name / "mem"))
        monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / name / "cfg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / name / "share"))
        config = tmp_path / name / "cfg"
        config.mkdir(parents=True, exist_ok=True)
        (config / "config.toml").write_text(f'[memory]\nshared = "{remote}"\n')
        for key, value in GIT_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / name / "gitconfig"))
        (tmp_path / name / "gitconfig").write_text(
            "[user]\n\tname = Alice\n\temail = a@example.invalid\n"
        )
        monkeypatch.chdir(tmp_path)
        return tmp_path / name / "mem"

    return use


def call(*argv: str) -> tuple[int, str, str]:
    out = Io()
    code = cli_memory.run(["memory", *argv], out)
    return code, out.stdout.getvalue(), out.stderr.getvalue()


def add_global(text: str = "shared lesson") -> str:
    code, out, err = call("add", "--scope", "global", "--text", text, "--json")
    assert code == 0, err
    return json.loads(out)["data"]["id"]


def merge_branch(checkout_remote: Path, tmp_path: Path, branch: str) -> None:
    """Merge a promote branch into main on the bare remote (a reviewer's act)."""
    reviewer = tmp_path / "reviewer"
    if not reviewer.exists():
        subprocess.run(
            ["git", "clone", str(checkout_remote), str(reviewer)],
            check=True,
            capture_output=True,
        )
    git(reviewer, "fetch", "origin")
    git(reviewer, "checkout", "main")
    git(
        reviewer,
        "-c",
        "user.name=R",
        "-c",
        "user.email=r@x",
        "merge",
        "--no-ff",
        "-m",
        "merge",
        f"origin/{branch}",
    )
    git(reviewer, "push", "origin", "main")


def test_promote_pull_roundtrip(tmp_path, remote, user) -> None:
    user("alice")
    entry_id = add_global()
    assert call("promote", entry_id)[0] == 2  # no checkout yet
    assert not share.checkout_path().exists()
    assert call("pull")[0] == 0
    assert (
        share.checkout_path()
        == tmp_path / "alice" / "share" / "varde" / "memory-shared"
    )

    code, out, err = call("promote", entry_id)
    assert code == 0, err
    checkout = share.checkout_path()
    assert git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert not (checkout / "global" / f"{entry_id}.md").exists()
    assert f"shared:{entry_id}" not in call("list")[1]
    assert call("promote", entry_id)[0] == 2  # branch exists
    assert git(remote, "log", "--oneline", "main").count("\n") == 0  # main untouched

    git(checkout, "push", "origin", f"promote/{entry_id}")
    user("bob")
    assert call("pull")[0] == 0
    assert call("list")[1] == ""  # unmerged branch invisible
    merge_branch(remote, tmp_path, f"promote/{entry_id}")
    assert call("pull")[0] == 0

    code, out, _ = call("list")
    assert code == 0 and f"shared:{entry_id} | global | shared lesson" in out
    assert out.strip().endswith("shared")
    code, shown, _ = call("show", f"shared:{entry_id}")
    assert code == 0 and "shared lesson" in shown
    assert "Alice" in shown and "/" not in shown.split("source:")[1].splitlines()[0]
    assert call("retire", f"shared:{entry_id}")[0] == 2
    assert (
        call(
            "reset",
            "--agent",
            f"shared:{entry_id}",
            "--model",
            "m",
            "--harness-version",
            "1",
        )[0]
        == 2
    )
    assert list(store.load_entries(user("bob"))) == []


def test_promote_rejections_and_unset_git_user(
    tmp_path, remote, user, monkeypatch
) -> None:
    user("alice")
    assert call("pull")[0] == 0
    project = call("add", "--scope", "project", "--text", "p", "--json")
    pid = json.loads(project[1])["data"]["id"]
    code, _, err = call("promote", pid)
    assert code == 2 and "project" in err
    root = store.memory_root(Path.cwd())
    secret = Entry(
        "sec1", "global", "", "api_key = abcdefgh12345678", "t", "2026-01-01T00:00:00Z"
    )
    with pytest.raises(share.ShareError):
        share.promote(secret, root)
    with_project = Entry(
        "wp1",
        "skill",
        "s",
        "x",
        "t",
        "2026-01-01T00:00:00Z",
        project="p-0123456789abcdef",
    )
    with pytest.raises(share.ShareError):
        share.promote(with_project, root)
    eid = add_global("ok")
    (tmp_path / "alice" / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in GIT_ENV:
        monkeypatch.delenv(key)
    monkeypatch.setenv("HOME", str(tmp_path / "nohome"))
    code, _, err = call("promote", eid)
    assert code == 2 and "user.name" in err


def test_pull_drops_bad_files_and_sanitizes(tmp_path, remote, user) -> None:
    user("alice")
    seed = tmp_path / "seed"
    good = (
        "---\nid: g1\nscope: global\nscope_key: ''\nsource: \"Bob\\u0007\"\n"
        "created: '2026-01-01T00:00:00Z'\nstatus: active\ntags: [\"a\\nb\"]\n---\n"
        "summary \x1b[31mred\n"
    )
    secret = good.replace("g1", "g2").replace("summary", "token = abcdefghijklmnop")
    for name, data in (("g1", good), ("g2", secret), ("bad", good)):
        (seed / "global").mkdir(exist_ok=True)
        (seed / "global" / f"{name}.md").write_text(data, encoding="utf-8")
    (seed / "global" / "..md").write_text(good, encoding="utf-8")
    (seed / "project" / "x-0123456789abcdef").mkdir(parents=True)
    (seed / "project" / "x-0123456789abcdef" / "p1.md").write_text(
        good.replace("global", "project")
    )
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "files")
    git(seed, "push", "origin", "main")
    assert call("pull")[0] == 0
    entries = share.load_shared()
    assert [e.id for e in entries] == ["g1"]
    assert "\x1b" not in entries[0].text and entries[0].tags == ("a b",)
    assert "\x07" not in entries[0].source


def test_surface_includes_shared_lines_without_bodies(tmp_path, remote, user) -> None:
    user("alice")
    entry_id = add_global("body line\nsecret body detail")
    assert call("pull")[0] == 0
    call("promote", entry_id)
    git(share.checkout_path(), "push", "origin", f"promote/{entry_id}")
    merge_branch(remote, tmp_path, f"promote/{entry_id}")
    call("pull")
    out = Io()
    assert cli_memory_surface.run(["surface"], out) == 0
    text = out.stdout.getvalue()
    assert f"shared:{entry_id} | global | body line" in text
    assert "secret body detail" not in text


def test_share_is_not_a_command() -> None:
    assert call("share")[0] == 2


def _promote_ready(user, tmp_path):
    user("alice")
    assert call("pull")[0] == 0
    return add_global("ok lesson")


def test_promote_id_already_in_shared_store_leaves_no_branch(
    tmp_path, remote, user
) -> None:
    entry_id = _promote_ready(user, tmp_path)
    assert call("promote", entry_id)[0] == 0
    git(share.checkout_path(), "push", "origin", f"promote/{entry_id}")
    merge_branch(remote, tmp_path, f"promote/{entry_id}")
    git(share.checkout_path(), "branch", "-D", f"promote/{entry_id}")
    assert call("pull")[0] == 0
    code, _, err = call("promote", entry_id)
    assert code == 2 and "already exists in the shared store" in err
    branches = git(share.checkout_path(), "branch", "--list", "promote/*")
    assert branches == ""


def test_promote_failure_deletes_branch_and_retry_succeeds(
    tmp_path, remote, user, monkeypatch
) -> None:
    entry_id = _promote_ready(user, tmp_path)
    real = store.write_entry
    calls = {"n": 0}

    def flaky(root, entry, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(root, entry, **kwargs)

    monkeypatch.setattr(store, "write_entry", flaky)
    code, _, err = call("promote", entry_id)
    assert code == 2 and "disk full" in err
    checkout = share.checkout_path()
    assert git(checkout, "branch", "--list", "promote/*") == ""
    assert git(checkout, "worktree", "list").count("\n") == 0
    assert call("promote", entry_id)[0] == 0
    assert git(checkout, "branch", "--list", f"promote/{entry_id}") != ""


def test_promote_requires_active_entry(tmp_path, remote, user) -> None:
    entry_id = _promote_ready(user, tmp_path)
    assert call("retire", entry_id)[0] == 0
    code, _, err = call("promote", entry_id)
    assert code == 2 and "only active" in err
    assert git(share.checkout_path(), "branch", "--list", "promote/*") == ""


def _push_shared(tmp_path, name, data) -> None:
    seed = tmp_path / "seed"
    (seed / "global").mkdir(exist_ok=True)
    (seed / "global" / f"{name}.md").write_text(data, encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-m", name)
    git(seed, "push", "origin", "main")


def _shared_doc(entry_id, created="2026-01-01T00:00:00Z", model="", body="lesson"):
    return (
        f"---\nid: {entry_id}\nscope: global\nscope_key: ''\nsource: s\n"
        f'created: "{created}"\nstatus: active\nmodel: "{model}"\n'
        f"tags: []\n---\n{body}\n"
    )


def test_shared_created_must_be_a_timestamp(tmp_path, remote, user) -> None:
    user("alice")
    _push_shared(tmp_path, "e1", _shared_doc("e1", created="2026-01-01\\x1b[31m"))
    _push_shared(tmp_path, "e2", _shared_doc("e2"))
    assert call("pull")[0] == 0
    entries, dropped = share.read_shared()
    assert [e.id for e in entries] == ["e2"]
    assert len(dropped) == 1 and "e1" in dropped[0]


def test_shared_model_is_single_line_and_capped(tmp_path, remote, user) -> None:
    user("alice")
    model = "m\\x1b[2Jx\\nsecond" + "z" * 200
    _push_shared(tmp_path, "m1", _shared_doc("m1", model=model))
    assert call("pull")[0] == 0
    (entry,) = share.load_shared()
    assert "\x1b" not in entry.model and "\n" not in entry.model
    assert len(entry.model) <= share.MAX_FIELD_CHARS


def test_oversize_shared_body_is_skipped_with_warning(
    tmp_path, remote, user, capsys
) -> None:
    user("alice")
    big = "x" * (share.MAX_TEXT_CHARS + 1)
    _push_shared(tmp_path, "big", _shared_doc("big", body=big))
    _push_shared(tmp_path, "ok", _shared_doc("ok"))
    code, out, _ = call("pull")
    err = capsys.readouterr().err
    assert code == 0 and "1 shared entries" in out
    assert "dropped shared global/big.md" in err and "exceeds" in err


def test_list_warns_about_dropped_files_but_load_does_not(
    tmp_path, remote, user, capsys
) -> None:
    user("alice")
    _push_shared(tmp_path, "big", _shared_doc("big", body="x" * 3000))
    assert call("pull")[0] == 0
    capsys.readouterr()
    assert share.load_shared() == []
    assert "dropped" not in capsys.readouterr().err
    call("list")
    assert "dropped shared" in capsys.readouterr().err
