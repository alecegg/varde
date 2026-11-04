# ruff: noqa: S603, S607
import subprocess
from dataclasses import replace
from typing import Any

import pytest
from varde_learn.memory import store
from varde_learn.memory.entry import Entry, EntryError

KEY = "My Repo_X-0123456789abcdef"


def make(**overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": "e1",
        "scope": "global",
        "scope_key": "",
        "text": "note\nbody",
        "source": "t",
        "created": "2026-11-01T00:00:00Z",
        "tags": ("a", "b"),
    }
    base.update(overrides)
    return Entry(**base)


def test_four_scope_layout_and_round_trip(tmp_path) -> None:
    entries = [
        make(id="g1"),
        make(
            id="a1", scope="agent", scope_key="builder", model="m", harness_version="1"
        ),
        make(id="s1", scope="skill", scope_key="varde-build", project=KEY),
        make(id="p1", scope="project", scope_key=KEY),
    ]
    for entry in entries:
        store.write_entry(tmp_path, entry)
    assert (tmp_path / "global" / "g1.md").is_file()
    assert (tmp_path / "agent" / "builder" / "a1.md").is_file()
    assert (tmp_path / "skill" / "varde-build" / "s1.md").is_file()
    assert (tmp_path / "project" / KEY / "p1.md").is_file()
    loaded = {e.id: e for e in store.load_entries(tmp_path)}
    assert loaded == {e.id: e for e in entries}
    assert loaded["a1"].model == "m"
    assert loaded["s1"].project == KEY


@pytest.mark.parametrize("entry_id", ["0123456789", "1e12345678", "true", "2026-11-01"])
def test_ids_that_look_like_other_yaml_types(tmp_path, entry_id) -> None:
    store.write_entry(tmp_path, make(id=entry_id))
    assert [e.id for e in store.load_entries(tmp_path)] == [entry_id]


def test_existing_entry_errors_unless_overwrite(tmp_path) -> None:
    store.write_entry(tmp_path, make())
    with pytest.raises(EntryError):
        store.write_entry(tmp_path, make())
    store.write_entry(tmp_path, make(text="new"), overwrite=True)
    assert next(store.load_entries(tmp_path)).text == "new"


def test_write_rejects_bad_keys(tmp_path) -> None:
    for key in (
        "../x-0123456789abcdef",
        "a/b-0123456789abcdef",
        "a\x01b-0123456789abcdef",
    ):
        with pytest.raises(EntryError):
            store.write_entry(tmp_path, make(scope="project", scope_key=key))
    with pytest.raises(EntryError):
        store.write_entry(tmp_path, make(scope="skill", scope_key=""))
    assert not any(tmp_path.rglob("*.md"))


def test_mismatched_frontmatter_is_skipped_with_warning(tmp_path, capsys) -> None:
    path = store.write_entry(tmp_path, make(id="g1"))
    moved = tmp_path / "global" / "other.md"
    path.rename(moved)
    other = tmp_path / "skill" / "k"
    other.mkdir(parents=True)
    (other / "g1.md").write_text(moved.read_text())
    assert list(store.load_entries(tmp_path)) == []
    err = capsys.readouterr().err
    assert "other.md" in err and "g1.md" in err


def test_unparseable_file_is_skipped(tmp_path, capsys) -> None:
    (tmp_path / "global").mkdir()
    (tmp_path / "global" / "bad.md").write_text("no frontmatter")
    assert list(store.load_entries(tmp_path)) == []
    assert "warning" in capsys.readouterr().err


def test_generate_id_is_deterministic_slug() -> None:
    first = store.generate_id("t", "global", "c")
    assert first == store.generate_id("t", "global", "c")
    assert first != store.generate_id("t2", "global", "c")
    assert store.entry_path(__import__("pathlib").Path("/r"), "global", "", first)


def test_set_status(tmp_path) -> None:
    entry = make()
    store.write_entry(tmp_path, entry)
    store.set_status(tmp_path, entry, "retired")
    assert next(store.load_entries(tmp_path)).status == "retired"


def git(*args, cwd) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@e.com",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_worktree_and_checkout_share_project_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    repo = tmp_path / "My Repo_X"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "f").write_text("x")
    git("add", "f", cwd=repo)
    git("commit", "-qm", "i", cwd=repo)
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "b", str(wt), cwd=repo)
    key = store.current_project_key(repo)
    assert key == store.current_project_key(wt)
    assert key.startswith("My Repo_X-")
    store.write_entry(tmp_path, make(scope="project", scope_key=key))


def test_memory_root_default_and_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("VARDE_MEMORY_DIR", raising=False)
    assert store.memory_root(tmp_path) == tmp_path / "share" / "varde" / "memory"
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "m"))
    assert store.memory_root(tmp_path) == tmp_path / "m"
    assert replace(make(), id="x").id == "x"


def test_unified_fields_round_trip_with_extra(tmp_path) -> None:
    entry = make(
        id="u1",
        type="decision",
        topic="storage",
        valid_until="2026-12-31",
        surface=False,
        updated="2026-11-02",
        title="Title",
        aliases=("one", "two"),
        description="Short.",
        extra={"owner": "me", "n": 3},
    )
    path = store.write_entry(tmp_path, entry)
    loaded = store.read_entry(path, tmp_path)
    assert loaded == entry
    assert loaded.extra == {"owner": "me", "n": 3}
    store.write_entry(tmp_path, loaded, overwrite=True)
    assert store.to_document(store.read_entry(path, tmp_path)) == path.read_text()


def test_old_file_loads_as_lesson_surfaced_and_stays_minimal(tmp_path) -> None:
    store.write_entry(tmp_path, make(id="old"))
    text = (tmp_path / "global" / "old.md").read_text()
    for key in ("type:", "surface:", "aliases:", "topic:"):
        assert key not in text
    loaded = store.read_entry(tmp_path / "global" / "old.md", tmp_path)
    assert (loaded.type, loaded.surface, loaded.extra) == ("lesson", True, {})


def test_load_report_lists_unreadable_files_as_issues(tmp_path) -> None:
    store.write_entry(tmp_path, make(id="ok"))
    bad = tmp_path / "global" / "bad.md"
    bad.write_text("no front matter\n")
    entries, issues = store.load_report(tmp_path)
    assert [e.id for e in entries] == ["ok"]
    assert [(i.code, i.path) for i in issues] == [("unreadable", str(bad))]
    assert [e.id for e in store.load_entries(tmp_path)] == ["ok"]


def test_secret_in_unified_entry_is_rejected(tmp_path) -> None:
    with pytest.raises(EntryError):
        store.write_entry(tmp_path, make(text="token = abcdefghijkl", type="decision"))
