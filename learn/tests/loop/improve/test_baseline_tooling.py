"""No-how baseline tooling: record, restore, verify, fills, candidates, reset."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from varde_core import skill_props
from varde_learn.docs import baseline_cmd
from varde_learn.docs.baseline import active_fills
from varde_learn.docs.cli import run as measure
from varde_learn.loop import (
    cli_skills_accept,
    cli_skills_candidates,
    cli_skills_fill,
    cli_skills_reset,
)
from varde_learn.loop.improve import candidates, fill, reset
from varde_learn.loop.improve import record as rec
from varde_learn.memory import store

SKILL = "demo"
BASE = "# Demo\n\n## Outcomes\n\nDone.\n\n## Validation\n\nCheck.\n"
FULL = BASE + "\n## Procedure\n\nStep one.\n\n## Topics\n\nhow: old - Old\n"
STEP = "---\ntopic: demo/step\nversion: 2\nsummary: s\n---\n\nStep body.\n"


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    pkg = repo / "mod" / "src" / "pkg"
    (pkg / "skills" / SKILL / "references").mkdir(parents=True)
    (pkg / "how" / SKILL).mkdir(parents=True)
    (pkg / "skills" / SKILL / "SKILL.md").write_text(BASE)
    (pkg / "skills" / SKILL / "references" / "r.md").write_text("ref\n")
    (pkg / "how" / SKILL / "step.md").write_text(STEP)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    baselines = tmp_path / "baselines"
    baselines.mkdir()
    (baselines / "MANIFEST.json").write_text(json.dumps({"skills": {}}))
    memory = tmp_path / "memory"
    monkeypatch.setattr(store, "memory_root", lambda _cwd: memory)
    return repo, pkg, baselines, memory


def record_baseline(repo: Path, baselines: Path, gen: str = "nohow1") -> int:
    return measure(
        ["baseline", "status", SKILL, "--baselines", str(baselines)]
        + ["--source", str(repo), "--record", "--gen", gen]
    )


def status(repo: Path, baselines: Path):
    packages = baseline_cmd.source_packages(repo)
    return baseline_cmd.statuses(baselines, repo, SKILL, packages)[0]


def test_record_writes_entry_tree_hash_and_slim_copy(world) -> None:
    repo, _, baselines, _ = world
    assert record_baseline(repo, baselines) == 0
    manifest = json.loads((baselines / "MANIFEST.json").read_text())
    [entry] = manifest["skills"][SKILL]["baselines"]
    tree = {
        "SKILL.md": BASE.encode(),
        "references/r.md": b"ref\n",
        "how/step.md": STEP.encode(),
    }
    assert entry["tree_hash"] == skill_props.tree_hash(tree)
    assert entry["how"]["step"]["version"] == 2
    assert f"{SKILL}/SKILL.md" in entry["files"]
    assert (baselines / "nohow1" / "slim" / SKILL / "SKILL.md").read_text() == BASE
    row = status(repo, baselines)
    assert row.tree_hash_match is True and row.drift is False


def test_record_leaves_out_evals_so_installed_check_is_clean(world, tmp_path) -> None:
    repo, pkg, baselines, _ = world
    evals = pkg / "skills" / SKILL / "evals"
    evals.mkdir()
    (evals / "evals.json").write_text("{}\n")
    assert record_baseline(repo, baselines) == 0
    manifest = json.loads((baselines / "MANIFEST.json").read_text())
    [entry] = manifest["skills"][SKILL]["baselines"]
    assert not any("evals" in path for path in entry["files"])
    assert not (baselines / "nohow1" / "slim" / SKILL / "evals").exists()
    assert status(repo, baselines).drift is False
    shipped = tmp_path / "shipped"
    shutil.copytree(pkg, shipped, ignore=shutil.ignore_patterns("evals"))
    row = baseline_cmd.statuses(baselines, repo, SKILL, [shipped])[0]
    assert row.drift is False and row.tree_hash_match is True


def test_record_lists_unpointed_topics_in_repo_file(world) -> None:
    repo, _, baselines, _ = world
    (repo / "core").mkdir()
    (repo / "core" / "how-unpointed.txt").write_text("how/other/x\n")
    assert record_baseline(repo, baselines) == 0
    listing = (repo / "core" / "how-unpointed.txt").read_text()
    assert listing == f"how/{SKILL}/step\nhow/other/x\n"


def test_check_flag_fails_on_mismatch_and_source_reads_checkout(world) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    args = ["baseline", "status", SKILL, "--baselines", str(baselines)]
    args += ["--source", str(repo), "--check"]
    assert measure(args) == 0
    (pkg / "skills" / SKILL / "SKILL.md").write_text(FULL)
    assert status(repo, baselines).tree_hash_match is False
    assert measure(args) == 1


def test_record_needs_source_and_gen(world) -> None:
    _, _, baselines, _ = world
    args = ["baseline", "status", SKILL, "--baselines", str(baselines), "--record"]
    assert measure(args) == 2


def test_plain_reset_has_no_pointer_and_no_topics_section() -> None:
    new, moved = reset.slim_text_plain(FULL)
    assert [m.step for m in moved] == ["procedure"]
    assert "how:" not in new and "## Topics" not in new
    assert new == BASE


def test_no_pointer_reset_cli_writes_pointer_free_proposal(world) -> None:
    _, pkg, _, memory = world
    (pkg / "skills" / SKILL / "SKILL.md").write_text(FULL)
    out = Io()
    args = [SKILL, "--model", "m", "--harness-version", "1", "--no-pointer"]
    code = cli_skills_reset.run(args, out, roots=[pkg], demand=lambda _s: {})
    assert code == 0
    [record] = rec.list_records(memory)
    diff = rec.read_diff(memory, record)
    assert "+how:" not in diff and "Topics" not in "".join(
        line for line in diff.splitlines() if line.startswith("+")
    )


def target_of(record: rec.LoopRecord) -> tuple[str, str]:
    target = reset.baseline_target(record)
    assert target is not None
    return target


def restore_args(baselines: Path, pkg: Path) -> list[str]:
    return [SKILL, "--to-baseline", "--baselines", str(baselines), "--root", str(pkg)]


def test_restore_proposal_accept_restores_exact_set(world, approve) -> None:
    repo, pkg, baselines, memory = world
    record_baseline(repo, baselines)
    skill_dir = pkg / "skills" / SKILL
    skill_dir.joinpath("SKILL.md").write_text(FULL)
    skill_dir.joinpath("references", "extra.md").write_text("extra\n")
    (pkg / "how" / SKILL / "step.md").write_text(STEP + "edit\n")
    out = Io()
    assert cli_skills_reset.run(restore_args(baselines, pkg), out) == 0
    [record] = rec.list_records(memory)
    assert "model" not in record.change and "+how:" not in rec.read_diff(memory, record)
    assert target_of(record)[0] == "nohow1"
    approve(memory, record.id)
    accepted = Io()
    assert cli_skills_accept.run([record.id, "--root", str(pkg)], accepted) == 0
    assert skill_dir.joinpath("SKILL.md").read_text() == BASE
    assert not skill_dir.joinpath("references", "extra.md").exists()
    assert (pkg / "how" / SKILL / "step.md").read_text() == STEP
    row = status(repo, baselines)
    assert row.tree_hash_match is True and row.drift is False


def test_restore_refuses_when_slim_copy_hash_differs(world) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    slim = baselines / "nohow1" / "slim" / SKILL / "SKILL.md"
    slim.write_text(BASE + "tampered\n")
    (pkg / "skills" / SKILL / "SKILL.md").write_text(FULL)
    out = Io()
    assert cli_skills_reset.run(restore_args(baselines, pkg), out) == 2
    assert "tree_hash" in out.stderr.getvalue()


def test_restore_at_baseline_is_refused(world) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    out = Io()
    assert cli_skills_reset.run(restore_args(baselines, pkg), out) == 2
    assert "already at baseline" in out.stderr.getvalue()


def test_accept_rolls_back_when_tree_hash_differs(world, approve) -> None:
    repo, pkg, baselines, memory = world
    record_baseline(repo, baselines)
    (pkg / "skills" / SKILL / "SKILL.md").write_text(FULL)
    cli_skills_reset.run(restore_args(baselines, pkg), Io())
    [record] = rec.list_records(memory)
    other = f"{target_of(record)[1]}".replace("0", "1", 1)
    forged = rec.LoopRecord(
        **{
            **record.__dict__,
            "change": record.change.replace(target_of(record)[1], other),
        }
    )
    rec.write_record(memory, forged)
    approve(memory, record.id)
    out = Io()
    assert cli_skills_accept.run([record.id, "--root", str(pkg)], out) == 2
    assert (pkg / "skills" / SKILL / "SKILL.md").read_text() == FULL


def test_installed_restore_sets_loop_hash_even_with_hand_edits(
    world, approve, tmp_path
) -> None:
    repo, _, baselines, memory = world
    record_baseline(repo, baselines)
    sync = tmp_path / "sync"
    installed = sync / SKILL
    (installed / "how").mkdir(parents=True)
    (installed / "references").mkdir()
    installed.joinpath("SKILL.md").write_text(FULL)
    installed.joinpath("references", "r.md").write_text("ref\n")
    installed.joinpath("how", "step.md").write_text(STEP)
    props = skill_props.Props(packaged_hash="old", loop_hash="")
    (installed / skill_props.SIDECAR).write_text(skill_props.render(props))
    out = Io()
    args = [SKILL, "--to-baseline", "--baselines", str(baselines)]
    assert cli_skills_reset.run(args, out, sync=sync) == 0
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    done = Io()
    assert cli_skills_accept.run([record.id], done, sync=sync) == 0
    sidecar = skill_props.parse((installed / skill_props.SIDECAR).read_text())
    assert sidecar.loop_hash == target_of(record)[1]
    assert skill_props.tree_hash(skill_props.disk_tree(installed)) == sidecar.loop_hash


def test_untracked_skill_is_reported_not_silently_skipped(world, approve, tmp_path):
    _, _, _, memory = world
    sync = tmp_path / "sync"
    installed = sync / SKILL
    installed.mkdir(parents=True)
    installed.joinpath("SKILL.md").write_text("old\n")
    (installed / skill_props.SIDECAR).write_text(
        skill_props.render(skill_props.Props(packaged_hash="x", loop_hash=""))
    )
    record = rec.LoopRecord(
        id="r-demo-aaaaaaa",
        skill=SKILL,
        direction="trim",
        change="edit demo",
        created="2026-11-02T00:00:00+00:00",
        pre_hashes={str(installed / "SKILL.md"): rec.hash_text("old\n")},
    )
    from varde_learn.loop.improve import extract

    diff = extract.render_diff(
        (extract.FileChange(str(installed / "SKILL.md"), "old\n", "new\n"),)
    )
    rec.write_record(memory, record, diff)
    approve(memory, record.id)
    out = Io()
    assert cli_skills_accept.run([record.id], out, sync=sync) == 0
    assert "hand-edited, loop-hash not recorded: demo" in out.stdout.getvalue()


def fill_args(baselines: Path, repo: Path, *extra: str) -> list[str]:
    return [SKILL, "--baselines", str(baselines), "--source", str(repo), *extra]


def test_fill_writes_line_and_measure_explains_the_change(world) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    (pkg / "skills" / SKILL / "SKILL.md").write_text(BASE + "\nRestored line.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fill")
    args = fill_args(baselines, repo, "--path", "SKILL.md", "--form", "text")
    args += ["--evidence", "fr-1", "--evidence", "fr-2", "--suspected-skips", "3"]
    out = Io()
    assert cli_skills_fill.run(args, out) == 0
    [line] = baseline_cmd.read_changelog(baselines / "changelog.jsonl")
    assert line["id"] == "fl-nohow1-001" and line["status"] == "active"
    assert line["evidence"]["friction"] == ["fr-1", "fr-2"]
    assert line["evidence"]["suspected_skips"] == 3
    assert line["tokens_added"] > 0
    assert line["commit"] == git(repo, "rev-parse", "HEAD")
    row = status(repo, baselines)
    assert row.drift is False and row.changes[0]["fill"] == line["id"]


def test_fill_needs_evidence_form_and_one_target(world) -> None:
    repo, _, baselines, _ = world
    record_baseline(repo, baselines)
    base = fill_args(baselines, repo)
    out = Io()
    assert (
        cli_skills_fill.run([*base, "--path", "SKILL.md", "--form", "text"], out) == 2
    )
    assert "evidence" in out.stderr.getvalue()
    both = [*base, "--path", "a", "--step", "s", "--form", "text", "--evidence", "x"]
    assert cli_skills_fill.run(both, Io()) == 2
    bad = [*base, "--step", "s", "--form", "nope", "--evidence", "x"]
    assert cli_skills_fill.run(bad, Io()) == 2


def test_retire_last_line_per_id_wins_and_ids_stay_unique(world) -> None:
    repo, _, baselines, _ = world
    record_baseline(repo, baselines)
    args = fill_args(baselines, repo, "--step", "demo/step", "--form", "how-line")
    args += ["--evidence", "fr-1", "--tokens-added", "5"]
    assert cli_skills_fill.run(args, Io()) == 0
    assert cli_skills_fill.run(args, Io()) == 0
    lines = baseline_cmd.read_changelog(baselines / "changelog.jsonl")
    assert [x["id"] for x in lines] == ["fl-nohow1-001", "fl-nohow1-002"]
    retire = [SKILL, "--baselines", str(baselines), "--retire", "fl-nohow1-001"]
    assert cli_skills_fill.run(retire, Io()) == 0
    lines = baseline_cmd.read_changelog(baselines / "changelog.jsonl")
    assert [x["id"] for x in active_fills(lines, SKILL, "nohow1")] == ["fl-nohow1-002"]
    assert (
        cli_skills_fill.run(
            [SKILL, "--baselines", str(baselines), "--retire", "all"], Io()
        )
        == 0
    )
    lines = baseline_cmd.read_changelog(baselines / "changelog.jsonl")
    assert active_fills(lines, SKILL, "nohow1") == []
    with pytest.raises(fill.FillError):
        fill.retire_lines(lines, SKILL, "nohow1", "fl-nohow1-009", "2026-01-01")


def history_rows(baselines: Path) -> list[dict]:
    out = Io()
    args = [SKILL, "--baselines", str(baselines), "--history", "--json"]
    assert cli_skills_fill.run(args, out) == 0
    return json.loads(out.stdout.getvalue())["data"]["fills"]


def test_history_survives_retire_reset_and_lists_retired(world, approve) -> None:
    repo, _, baselines, _ = world
    record_baseline(repo, baselines)
    args = fill_args(baselines, repo, "--step", "demo/step", "--form", "how-line")
    args += ["--evidence", "fr-1", "--tokens-added", "5"]
    assert cli_skills_fill.run(args, Io()) == 0
    retire = [SKILL, "--baselines", str(baselines), "--retire", "all"]
    assert cli_skills_fill.run(retire, Io()) == 0
    changelog = baselines / "changelog.jsonl"
    before = changelog.read_text()
    (world[1] / "skills" / SKILL / "references" / "extra.md").write_text("x\n")
    assert accept_restore(world, approve) == 0
    record_baseline(repo, baselines)
    assert changelog.read_text().startswith(before)
    [row] = history_rows(baselines)
    assert row["id"] == "fl-nohow1-001" and row["state"] == "retired"
    assert row["step"] == "demo/step" and row["evidence"] == ["fr-1"]
    assert row["tokens_added"] == 5 and row["retired_at"] and row["added_at"]
    assert row["commit"]
    text = Io()
    plain = [SKILL, "--baselines", str(baselines), "--history"]
    assert cli_skills_fill.run(plain, text) == 0
    assert "fl-nohow1-001 retired demo/step" in text.stdout.getvalue()


def test_readd_after_retire_gets_new_id_and_links_earlier(world) -> None:
    repo, _, baselines, _ = world
    record_baseline(repo, baselines)
    args = fill_args(baselines, repo, "--step", "demo/step", "--form", "how-line")
    args += ["--evidence", "fr-1", "--tokens-added", "5"]
    assert cli_skills_fill.run(args, Io()) == 0
    retire = [SKILL, "--baselines", str(baselines), "--retire", "all"]
    assert cli_skills_fill.run(retire, Io()) == 0
    assert cli_skills_fill.run(args, Io()) == 0
    first, second = history_rows(baselines)
    assert first["state"] == "retired" and first["supersedes"] is None
    assert second["id"] == "fl-nohow1-002" and second["state"] == "active"
    assert second["supersedes"] == first["id"]
    lines = baseline_cmd.read_changelog(baselines / "changelog.jsonl")
    assert [x["id"] for x in active_fills(lines, SKILL, "nohow1")] == [second["id"]]


def demand_with(friction: bool) -> dict:
    row = {"step": f"{SKILL}/step", "requests": 2, "failures": 0, "friction": 1}
    row["friction_ids"] = ["fr-7"] if friction else []
    skill = {"skill": SKILL, "friction_items": int(friction), "how_skip_friction": 0}
    return {"steps": [row], "skills": [skill | {"suspected_skips": 4}]}


def test_candidates_at_baseline_never_reset_or_trim() -> None:
    targets = [candidates.Target(SKILL, "skill", 9000)]
    at = {SKILL: candidates.BaselineState("nohow1", True)}
    groups = candidates.rank(targets, {}, baselines=at)
    assert all(not items for items in groups.values())
    drifted = {SKILL: candidates.BaselineState("nohow1", False)}
    [row] = candidates.rank(targets, {}, baselines=drifted)["reset"]
    assert row.baseline == "nohow1"
    assert "baseline restore (nohow1)" in candidates.format_text(
        {"add": [], "trim": [], "reset": [row]}
    )
    [plain] = candidates.rank(targets, {})["reset"]
    assert "baseline restore" not in candidates.format_text(
        {"add": [], "trim": [], "reset": [plain]}
    )


def test_candidates_add_carries_fill_evidence_block() -> None:
    targets = [candidates.Target(SKILL, "skill", 300)]
    at = {SKILL: candidates.BaselineState("nohow1", True)}
    demand = demand_with(friction=True)
    demand["skills"][0]["friction_items"] = 1
    [row] = candidates.rank(targets, demand, baselines=at)["add"]
    assert row.evidence == {
        "friction": ["fr-7"],
        "suspected_skips": 4,
        "how_requests": 2,
    }
    assert "fill evidence" in candidates.format_text(
        {"add": [row], "trim": [], "reset": []}
    )


def test_candidates_cli_reads_baselines(world, monkeypatch) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    monkeypatch.setattr(baseline_cmd, "provider_packages", lambda: [pkg])
    out = Io()
    code = cli_skills_candidates.run(
        [str(pkg), "--baselines", str(baselines), "--json"], out, demand=dict
    )
    assert code == 0


def accept_restore(world, approve) -> int:
    _, pkg, baselines, memory = world
    assert cli_skills_reset.run(restore_args(baselines, pkg), Io()) == 0
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    return cli_skills_accept.run([record.id, "--root", str(pkg)], Io())


def test_restore_deletes_extra_file(world, approve) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    extra = pkg / "skills" / SKILL / "references" / "extra.md"
    extra.write_text("extra\n")
    assert accept_restore(world, approve) == 0
    assert not extra.exists()


def test_restore_deletes_empty_extra_file(world, approve) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    extra = pkg / "skills" / SKILL / "references" / "empty.md"
    extra.write_text("")
    assert accept_restore(world, approve) == 0
    assert not extra.exists()
    assert status(repo, baselines).tree_hash_match is True


def test_restore_when_only_a_how_topic_drifted(world, approve) -> None:
    repo, pkg, baselines, _ = world
    record_baseline(repo, baselines)
    topic = pkg / "how" / SKILL / "step.md"
    topic.write_text(STEP + "edit\n")
    assert accept_restore(world, approve) == 0
    assert topic.read_text() == STEP
    assert status(repo, baselines).tree_hash_match is True


def test_accept_refuses_paths_outside_roots(world, approve, tmp_path) -> None:
    repo, pkg, baselines, memory = world
    record_baseline(repo, baselines)
    extra = pkg / "skills" / SKILL / "references" / "extra.md"
    extra.write_text("extra\n")
    assert cli_skills_reset.run(restore_args(baselines, pkg), Io()) == 0
    [record] = rec.list_records(memory)
    approve(memory, record.id)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = Io()
    assert cli_skills_accept.run([record.id, "--root", str(elsewhere)], out) == 2
    assert extra.exists()


def test_record_refuses_a_repeated_gen(world) -> None:
    repo, _, baselines, _ = world
    assert record_baseline(repo, baselines) == 0
    assert record_baseline(repo, baselines) != 0
    manifest = json.loads((baselines / "MANIFEST.json").read_text())
    assert len(manifest["skills"][SKILL]["baselines"]) == 1
