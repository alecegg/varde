"""``varde learn how``: topic discovery, listing, bodies, errors, wheel packaging."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from varde_learn.docs import how_cmd
from varde_learn.docs.cli import run

ROOT = Path(__file__).resolve().parents[3]
TOPIC = (
    "---\ntopic: demo/first\nversion: 2\nsummary: Do the first thing\n"
    "---\n\nBody line.\n"
)


@pytest.fixture
def how_root(tmp_path, monkeypatch):
    root = tmp_path / "how"
    (root / "demo").mkdir(parents=True)
    (root / "demo" / "first.md").write_text(TOPIC)
    (root / "demo" / "second.md").write_text(TOPIC.replace("first", "second"))
    monkeypatch.setattr(how_cmd, "provider_roots", lambda: [root])
    monkeypatch.setattr(how_cmd, "agent_roots", list)
    return root


def test_parse_topic_reads_frontmatter_and_body():
    topic = how_cmd.parse_topic("demo", "first", TOPIC)
    assert (topic.id, topic.version, topic.summary) == (
        "demo/first",
        2,
        "Do the first thing",
    )
    assert topic.body == "Body line."


def test_parse_topic_rejects_missing_fields():
    with pytest.raises(ValueError, match="lacks 'summary'"):
        how_cmd.parse_topic("demo", "x", "---\ntopic: a\nversion: 1\n---\nb\n")
    with pytest.raises(ValueError, match="missing frontmatter"):
        how_cmd.parse_topic("demo", "x", "no frontmatter")


def test_list_steps_one_line_each(how_root, capsys):
    assert run(["how", "demo"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "first - Do the first thing",
        "second - Do the second thing",
    ]


def test_step_prints_body(how_root, capsys):
    assert run(["how", "demo", "first"]) == 0
    assert capsys.readouterr().out == "Body line.\n"


def test_json_list_and_body(how_root, capsys):
    assert run(["how", "--json", "demo"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [row["id"] for row in data["steps"]] == ["demo/first", "demo/second"]
    assert run(["how", "demo", "first", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["body"] == "Body line."


def test_agent_topics_served_and_skills_win(how_root, tmp_path, monkeypatch, capsys):
    agents = tmp_path / "agents"
    (agents / "bot" / "how").mkdir(parents=True)
    (agents / "bot" / "how" / "go.md").write_text(TOPIC.replace("demo/first", "bot/go"))
    (agents / "demo" / "how").mkdir(parents=True)
    (agents / "demo" / "how" / "agent-only.md").write_text(TOPIC)
    (agents / "nohow").mkdir()
    monkeypatch.setattr(how_cmd, "agent_roots", lambda: [agents])
    assert run(["how", "bot", "go"]) == 0
    assert capsys.readouterr().out.strip() == "Body line."
    assert run(["how", "demo"]) == 0
    assert "agent-only" not in capsys.readouterr().out
    assert run(["how", "nohow"]) == 1


def test_unknown_skill_and_step_name_valid_ids(how_root, capsys):
    assert run(["how", "nope"]) == 1
    assert "valid skills: demo" in capsys.readouterr().err
    assert run(["how", "demo", "nope"]) == 1
    assert "valid steps: first, second" in capsys.readouterr().err


def test_missing_skill_is_a_usage_error(how_root, capsys):
    assert run(["how"]) == 2
    assert "<SKILL>" in capsys.readouterr().err


def test_help_exits_zero(capsys):
    assert run(["how", "--help"]) == 0
    assert "Usage: varde learn how" in capsys.readouterr().out


def test_real_providers_discover_without_error():
    how_cmd.load_topics(how_cmd.provider_roots())


@pytest.mark.slow
def test_how_tree_builds_into_wheel_and_sync_ignores_it(tmp_path):
    package = tmp_path / "learn"
    shutil.copytree(
        ROOT / "learn", package, ignore=shutil.ignore_patterns("tests", "__pycache__")
    )
    how = package / "src/varde_learn/how/demo"
    how.mkdir(parents=True)
    (how / "first.md").write_text(TOPIC)
    out = tmp_path / "out"
    subprocess.run(  # noqa: S603 - fixed argv
        ["uv", "build", "--wheel", "--out-dir", str(out), str(package)],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    with zipfile.ZipFile(next(out.glob("*.whl"))) as wheel:
        assert "varde_learn/how/demo/first.md" in wheel.namelist()


def tracked_how_files() -> list[Path]:
    return sorted((ROOT / "learn/src/varde_learn/how").rglob("*.md"))


@pytest.mark.slow
def test_setup_sync_installs_how_tree_and_keeps_source(tmp_path, monkeypatch):
    """Sync installs how topics into the skill dir; the source tree is unchanged."""
    before = tracked_how_files()
    assert before, "pilot topics missing"
    for name, value in {
        "HOME": tmp_path,
        "XDG_CONFIG_HOME": tmp_path / "xdg",
        "VARDE_CONFIG_DIR": tmp_path / "cfg",
    }.items():
        monkeypatch.setenv(name, str(value))
    skills = tmp_path / "skills"
    subprocess.run(  # noqa: S603 - fixed argv
        [  # noqa: S607
            "uv",
            "run",
            "--offline",
            "varde",
            "setup",
            "sync",
            "--skills-dir",
            str(skills),
            "--agents-dir",
            str(tmp_path / "agents"),
            "--harnesses",
            "none",
            "--link-mode",
            "copy",
            "--preset",
            "learn",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert (skills / "varde-docs/SKILL.md").is_file()
    assert (skills / "varde-docs/how").is_dir()
    assert tracked_how_files() == before
