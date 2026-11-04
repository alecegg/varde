from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from varde_learn.loop import cli_skills_extract
from varde_learn.loop.improve import extract, filediff, tool_entry
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

HEAD = "---\ntopic: varde-x/{}\nversion: {}\nsummary: S\n"
TOPIC = (
    HEAD.format("do", 2)
    + "---\n\nStep one is to read the input files and list what changed.\n"
    + "Step two with more words to count, covering every changed file.\n"
)
JUDGE = HEAD.format("pick", 1) + "judgment: true\n---\n\nChoose well.\n"
INSTRUCTIONS = (
    "# Agent\n\nIntro.\n\n## Checks\n\n"
    "Run the checks carefully, one by one, and read every failure in full.\n"
    "Then stop and report each result to the caller with evidence.\n\n"
    "## Handoff\n\nReport back.\n"
)


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def world(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg"
    (pkg / "how" / "varde-x").mkdir(parents=True)
    (pkg / "how" / "varde-x" / "do.md").write_text(TOPIC)
    (pkg / "how" / "varde-x" / "pick.md").write_text(JUDGE)
    agents = pkg / "agents"
    (agents / "varde-y").mkdir(parents=True)
    variant = agents / "varde-y" / "claude.md"
    variant.write_text("<!-- varde-generated-agent -->\n" + INSTRUCTIONS)
    caps = {
        "version": 1,
        "profiles": [{"name": "varde-y", "instructions": INSTRUCTIONS}],
    }
    (agents / "capabilities.json").write_text(json.dumps(caps, indent=2) + "\n")
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    return pkg, memory


def snapshot(root: Path) -> dict[str, str]:
    return {str(p): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def run(args, pkg):
    out = Io()
    return cli_skills_extract.run(args, out, roots=[pkg]), out


def test_dry_run_writes_nothing(world) -> None:
    pkg, memory = world
    before = snapshot(pkg)
    code, out = run(["varde-x", "do", "--dry-run"], pkg)
    assert code == 0
    assert "STEP_TEXT" in out.stdout.getvalue()
    assert not memory.exists()
    assert snapshot(pkg) == before


def test_real_run_writes_proposal_and_leaves_files_unchanged(world) -> None:
    pkg, memory = world
    before = snapshot(pkg)
    code, _ = run(["varde-x", "do"], pkg)
    assert code == 0
    assert snapshot(pkg) == before
    [record] = rec.list_records(memory)
    assert record.state == "proposed"
    assert record.direction == "trim"
    assert record.token_delta < 0
    diff = rec.read_diff(memory, record)
    paths = {f.path.removeprefix(str(pkg)) for f in filediff.parse_diff(diff)}
    assert paths == {
        "/how/varde-x/do.md",
        "/step_tools/varde-x/do.py",
        "/step_tools/registry.toml",
    }
    assert set(record.pre_hashes.values()) >= {filediff.ABSENT}


def test_diff_post_image_keeps_the_step_text_in_the_tool(world) -> None:
    pkg, memory = world
    run(["varde-x", "do"], pkg)
    [record] = rec.list_records(memory)
    new = {f.path: f for f in filediff.parse_diff(rec.read_diff(memory, record))}
    tool = filediff.apply_file_diff("", new[str(pkg / "step_tools/varde-x/do.py")])
    namespace: dict = {}
    exec(tool, namespace)  # noqa: S102 - generated fixture tool
    assert "Step two with more words" in namespace["STEP_TEXT"]
    topic = filediff.apply_file_diff(TOPIC, new[str(pkg / "how/varde-x/do.md")])
    assert 'step-tool" varde-x/do' in topic
    assert "Step one is" not in topic and "version: 2" in topic
    registry = filediff.apply_file_diff("", new[str(pkg / "step_tools/registry.toml")])
    assert [r.step for r in tool_entry.parse_registry(registry)] == ["do"]


def test_judgment_step_rejected(world) -> None:
    pkg, memory = world
    code, out = run(["varde-x", "pick"], pkg)
    assert code == 2
    assert "judgment" in out.stderr.getvalue()
    assert not memory.exists()


def test_unknown_step_and_usage_errors(world) -> None:
    pkg, _ = world
    assert run(["varde-x", "nope"], pkg)[0] == 2
    assert run(["varde-x", "a", "b"], pkg)[0] == 2


def test_agent_target_diffs_capabilities_and_new_topic_not_variants(world) -> None:
    pkg, memory = world
    before = snapshot(pkg)
    code, _ = run(["varde-y", "checks"], pkg)
    assert code == 0
    assert snapshot(pkg) == before
    [record] = rec.list_records(memory)
    diff = rec.read_diff(memory, record)
    paths = {f.path.removeprefix(str(pkg)) for f in filediff.parse_diff(diff)}
    assert "/agents/capabilities.json" in paths
    assert "/agents/varde-y/how/checks.md" in paths
    assert not any(path.endswith("claude.md") for path in paths)
    by_path = {f.path: f for f in filediff.parse_diff(diff)}
    caps_text = (pkg / "agents/capabilities.json").read_text()
    new_caps = filediff.apply_file_diff(
        caps_text, by_path[str(pkg / "agents/capabilities.json")]
    )
    instructions = json.loads(new_caps)["profiles"][0]["instructions"]
    assert "Run the checks carefully" not in instructions
    assert "## Handoff\n\nReport back." in instructions
    topic = filediff.apply_file_diff(
        "", by_path[str(pkg / "agents/varde-y/how/checks.md")]
    )
    assert "Run the checks carefully," in topic
    assert record.token_delta < 0


def test_agent_judgment_section_rejected() -> None:
    text = "# A\n\n## Pick\n\n<!-- judgment -->\nChoose.\n"
    caps = json.dumps({"profiles": [{"name": "a", "instructions": text}]})
    with pytest.raises(extract.ExtractError, match="judgment"):
        extract.plan_agent_step(
            "a", "pick", Path("/c.json"), caps, Path("/a"), extract.Existing()
        )


def test_already_extracted_step_is_refused() -> None:
    row = tool_entry.ToolRow("varde-x", "do", "varde-x/do.py")
    registry = tool_entry.add_row("", row)
    with pytest.raises(extract.ExtractError, match="already"):
        extract.plan_skill_step(
            "varde-x",
            "do",
            Path("/t.md"),
            TOPIC,
            Path("/p"),
            extract.Existing(registry),
        )
