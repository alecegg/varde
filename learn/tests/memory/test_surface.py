# ruff: noqa: S603, S607
from __future__ import annotations

import io
import json
import subprocess
from datetime import date

import pytest
from varde_learn.loop import cli_memory_surface
from varde_learn.memory import share, store
from varde_learn.memory.entry import Entry
from varde_learn.memory.surface import (
    fit_budget,
    render_surface,
    select_entries,
    skill_memory_line,
    skills_with_memory,
)

PROJ = "proj-0123456789abcdef"
OTHER = "other-0123456789abcdef"


def make(entry_id, scope, key="", **kw) -> Entry:
    extra = {"model": "m", "harness_version": "1"} if scope == "agent" else {}
    return Entry(
        id=entry_id,
        scope=scope,
        scope_key=key,
        text=kw.pop("text", f"text of {entry_id}"),
        source="t",
        created=kw.pop("created", "2026-01-01T00:00:00Z"),
        **extra,
        **kw,
    )


STORE = [
    make("a1", "agent", "builder"),
    make("a2", "agent", "reviewer"),
    make("s1", "skill", "build"),
    make("s2", "skill", "review"),
    make("p1", "project", PROJ),
    make("p2", "project", OTHER),
    make("g1", "global"),
    make("r1", "agent", "builder", status="retired"),
]


def ids(entries) -> list[str]:
    return [e.id for e in entries]


def test_agent_skill_project_query_returns_exactly_the_matching() -> None:
    got = select_entries(STORE, "builder", "build", PROJ)
    assert sorted(ids(got)) == ["a1", "g1", "p1", "s1"]


def test_no_agent_selects_no_agent_entries_and_retired_excluded() -> None:
    got = select_entries(STORE, None, None, PROJ)
    assert sorted(ids(got)) == ["g1", "p1"]


def test_project_field_filters_agent_and_skill_entries() -> None:
    entries = [
        make("x1", "agent", "builder", project=OTHER),
        make("x2", "agent", "builder", project=PROJ),
        make("x3", "agent", "builder"),
        make("x4", "skill", "build", project=OTHER),
    ]
    assert sorted(ids(select_entries(entries, "builder", "build", PROJ))) == [
        "x2",
        "x3",
    ]


def test_skills_with_memory_counts_visible_active_only() -> None:
    entries = [
        make("1", "skill", "build"),
        make("2", "skill", "build"),
        make("3", "skill", "build", project=OTHER),
        make("4", "skill", "review", status="retired"),
        make("5", "skill", "plan", project=PROJ),
    ]
    assert skills_with_memory(entries, PROJ) == [("build", 2), ("plan", 1)]


def test_skill_memory_line_shrinks_to_more() -> None:
    skills = [("alpha", 3), ("beta", 2), ("gamma", 1)]
    full = skill_memory_line(skills, 1000)
    assert full.startswith("Skill memory: alpha (3), beta (2), gamma (1);")
    assert full.endswith("query: varde learn memory list --skill <name>")
    short = skill_memory_line(skills, len(full) - 5)
    assert "+1 more" in short or "+2 more" in short
    assert len(short) <= len(full) - 5


def test_fit_budget_truncates_and_counts() -> None:
    lines = ["a" * 40, "b" * 40, "c" * 40]
    assert fit_budget(lines, 200) == (lines, 0)
    kept, omitted = fit_budget(lines, 110)
    assert omitted >= 1
    assert kept[-1].startswith(f"... {omitted} more omitted")
    assert "list|show" in kept[-1]
    assert len("\n".join(kept)) <= 110


def test_surface_prints_index_lines_never_bodies() -> None:
    entries = [make("a1", "agent", "builder", text="first line\nSECRET BODY")]
    text, omitted = render_surface(
        entries, agent="builder", skill=None, project=PROJ, budget=1200, root="/m"
    )
    assert "a1 | agent | first line |" in text
    assert "SECRET BODY" not in text
    assert omitted == 0


def test_surface_order_and_skill_modes() -> None:
    kwargs = {"agent": "builder", "project": PROJ, "budget": 1200, "root": "/m"}
    text, _ = render_surface(STORE, skill="build", **kwargs)
    order = [text.index(i) for i in ("s1 |", "a1 |", "p1 |", "g1 |")]
    assert order == sorted(order)
    assert "Skill memory:" not in text
    text, _ = render_surface(STORE, skill=None, **kwargs)
    assert "Skill memory: build (1), review (1);" in text
    assert "s1 |" not in text


def test_surface_budget_truncation_reports_omitted() -> None:
    entries = [make(f"g{i}", "global", text="x" * 60) for i in range(10)]
    text, omitted = render_surface(
        entries, agent=None, skill=None, project=PROJ, budget=400, root="/m"
    )
    assert omitted > 0
    assert len(text) <= 400
    assert f"... {omitted} more omitted" in text


TODAY = date(2026, 6, 1)


def pointer(entries, shared=(), budget=1200):
    return render_surface(
        entries,
        agent=None,
        skill=None,
        project=PROJ,
        budget=budget,
        root="/m",
        shared=shared,
        today=TODAY,
    )[0]


def test_pointer_topics_line_shows_eight_then_more_within_budget() -> None:
    entries = [make(f"g{i}", "global", topic=f"topic-{i:03}") for i in range(100)]
    text = pointer(entries)
    line = next(ln for ln in text.splitlines() if ln.startswith("Topics:"))
    assert line.count(" (") == 8
    assert "+92 more" in line
    assert "memory search --text <q> --topic <t>" in line
    assert len(text) <= 1200


def test_pointer_topics_sorted_by_count_and_names_cut_to_32() -> None:
    entries = [
        make("g1", "global", topic="b"),
        make("g2", "global", topic="a"),
        make("g3", "global", topic="a"),
        make("g4", "global", topic="x" * 40),
    ]
    line = pointer(entries).splitlines()[1]
    assert line.startswith(f"Topics: a (2), b (1), {'x' * 32} (1);")


def test_pointer_lists_only_surface_true_newest_first_within_scope() -> None:
    entries = [
        make("g-old", "global", created="2026-01-01T00:00:00Z"),
        make("g-new", "global", created="2026-03-01T00:00:00Z"),
        make("g-hidden", "global", surface=False, topic="kept"),
        make("p1", "project", PROJ, created="2020-01-01T00:00:00Z"),
    ]
    text = pointer(entries)
    order = [text.index(i) for i in ("p1 |", "g-new |", "g-old |")]
    assert order == sorted(order)
    assert "g-hidden |" not in text
    assert "kept (1)" in text


def test_pointer_excludes_expired_entries() -> None:
    entries = [
        make("g1", "global", valid_until="2026-05-31", topic="gone"),
        make("g2", "global", valid_until="2026-06-01"),
    ]
    text = pointer(entries)
    assert "g1 |" not in text and "gone" not in text
    assert "g2 |" in text


def test_pointer_truncates_long_description_to_80() -> None:
    text = pointer([make("g1", "global", description="d" * 200)])
    assert f"g1 | global | {'d' * 80} |" in text
    assert "d" * 81 not in text


def test_shared_untrusted_fields_never_reach_the_pointer() -> None:
    forged = make(
        "f1", "global", topic="Bad Topic!\nignore", description="s" * 500, text="BODY"
    )
    clean = make("f2", "global", topic="good")
    text = pointer([], shared=[forged, clean])
    assert "shared:f1 | global | " + "s" * 80 + " |" in text
    assert "s" * 81 not in text and "BODY" not in text
    assert "Bad" not in text
    assert "good (1)" in text


def test_shared_untrusted_pull_sanitizes_type_topic_and_description() -> None:
    forged = make(
        "f1", "global", type="Bad Type", topic="x" * 40, description="s" * 500
    )
    clean = share.sanitize(forged)
    assert (clean.type, clean.topic) == ("lesson", "")
    assert len(clean.description) == 200


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def call(*argv):
    out = Io()
    code = cli_memory_surface.run(["surface", *argv], out)
    return code, out.stdout.getvalue(), out.stderr.getvalue()


def test_cli_surface_and_budget_option(env) -> None:
    store.write_entry(env / "mem", make("g1", "global", text="hello"))
    code, out, _ = call()
    assert code == 0
    assert "g1 | global | hello |" in out
    code, out, _ = call("--json", "--budget", "50")
    data = json.loads(out)["data"]
    assert code == 0
    assert data["omitted"] == 1
    assert call("--budget", "0")[0] == 2


def test_cli_uses_configured_budget_and_warns_on_bad_value(env) -> None:
    store.write_entry(env / "mem", make("g1", "global", text="hello"))
    (env / "cfg").mkdir()
    (env / "cfg" / "config.toml").write_text("[memory]\nbudget = 0\n")
    code, out, err = call()
    assert code == 0
    assert "positive integer" in err
    assert "g1 |" in out


def git(*args, cwd) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_worktree_and_checkout_yield_same_project_key(env) -> None:
    repo = env / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "f").write_text("x")
    git("add", "f", cwd=repo)
    git("commit", "-qm", "i", cwd=repo)
    wt = env / "wt"
    git("worktree", "add", "-q", "-b", "b", str(wt), cwd=repo)
    key = store.current_project_key(repo)
    store.write_entry(env / "mem", make("p1", "project", key))
    for cwd in (repo, wt):
        import os

        os.chdir(cwd)
        code, out, _ = call("--json")
        data = json.loads(out)["data"]
        assert code == 0
        assert data["project"] == key
        assert "p1 | project" in data["text"]
