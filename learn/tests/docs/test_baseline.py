"""``varde learn measure <skill> baseline``: manifest, changelog and drift fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from varde_learn.docs import baseline_cmd
from varde_learn.docs.baseline import changed_refs, diff_size, sha256_text
from varde_learn.docs.cli import run

SKILL = "demo"
SKILL_TEXT = "# Demo\n\nOne line.\n"
STEP_TEXT = "---\ntopic: demo/step\nversion: 1\nsummary: s\n---\n\nStep body.\n"


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def sha(text: str) -> str:
    return sha256_text(text.encode())


def entry(gen: str, skill_text: str, step_text: str) -> dict:
    return {
        "gen": gen,
        "tag": f"skills-slim-{gen}",
        "commit": "c",
        "date": "2026-10-30",
        "files": {f"{SKILL}/SKILL.md": sha(skill_text)},
        "how": {"step": {"version": 1, "sha256": sha(step_text)}},
    }


class Fixture:
    def __init__(self, tmp_path: Path):
        self.repo = tmp_path / "repo"
        self.pkg = self.repo / "pkg"
        (self.pkg / "skills" / SKILL).mkdir(parents=True)
        (self.pkg / "how" / SKILL).mkdir(parents=True)
        self.baselines = tmp_path / "baselines"
        self.baselines.mkdir()
        git(self.repo, "init", "-q")
        self.write_skill(SKILL_TEXT)
        self.write_step(STEP_TEXT)
        self.commit("base")
        self.manifest = {
            "generations": [{"index": 1, "gen": "g1", "date": "2026-10-30"}],
            "skills": {
                SKILL: {
                    "original": {"tag": "skills-orig-g1", "commit": "o", "files": {}},
                    "baselines": [entry("g1", SKILL_TEXT, STEP_TEXT)],
                    "fills": [],
                }
            },
        }
        self.changelog: list[dict] = []

    def write_skill(self, text: str) -> None:
        (self.pkg / "skills" / SKILL / "SKILL.md").write_text(text)

    def write_step(self, text: str) -> None:
        (self.pkg / "how" / SKILL / "step.md").write_text(text)

    def commit(self, message: str) -> str:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def fill(self, fill_id: str, commit: str, **fields) -> None:
        self.changelog.append(
            {
                "id": fill_id,
                "kind": "fill",
                "skill": SKILL,
                "gen": "g1",
                "status": "active",
                "commit": commit,
                "tokens_added": 7,
                **fields,
            }
        )

    def status(self):
        (self.baselines / "MANIFEST.json").write_text(json.dumps(self.manifest))
        (self.baselines / "changelog.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in self.changelog)
        )
        return baseline_cmd.statuses(self.baselines, self.repo, None, [self.pkg])[0]


@pytest.fixture
def fx(tmp_path):
    return Fixture(tmp_path)


def test_clean_skill_has_no_drift(fx):
    status = fx.status()
    assert status.drift is False
    assert status.changes == []
    assert status.baseline["gen"] == "g1"
    assert status.original["tag"] == "skills-orig-g1"


def test_fill_with_changelog_line_is_explained(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    commit = fx.commit("fill")
    fx.fill("fill-g1-001", commit, path="SKILL.md", step="")
    status = fx.status()
    assert status.drift is False
    assert status.changes == [
        {"ref": "demo/SKILL.md", "change": "changed", "fill": "fill-g1-001"}
    ]
    assert status.fills[0]["fill"] == "fill-g1-001"
    assert status.fills[0]["tokens_added"] == 7


def test_fill_without_changelog_line_is_drift(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    fx.commit("unrecorded")
    status = fx.status()
    assert status.drift is True
    assert status.changes[0]["fill"] is None


def test_fill_whose_commit_does_not_touch_the_file_is_drift(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    fx.commit("edit")
    (fx.repo / "other.txt").write_text("x")
    other = fx.commit("other")
    fx.fill("fill-g1-001", other, path="SKILL.md")
    assert fx.status().drift is True


def test_unrecorded_step_edit_is_drift_even_when_a_fill_names_the_skill_file(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    fx.write_step(STEP_TEXT + "More.\n")
    commit = fx.commit("both")
    fx.fill("fill-g1-001", commit, path="SKILL.md")
    status = fx.status()
    assert status.drift is True
    by_ref = {c["ref"]: c["fill"] for c in status.changes}
    assert by_ref == {"demo/SKILL.md": "fill-g1-001", "how/demo/step": None}


def test_fill_naming_a_step_explains_the_step_edit(fx):
    fx.write_step(STEP_TEXT + "More.\n")
    commit = fx.commit("step")
    fx.fill("fill-g1-001", commit, step="demo/step", path="")
    assert fx.status().drift is False


def test_dropped_fill_does_not_explain(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    commit = fx.commit("fill")
    fx.fill("fill-g1-001", commit, path="SKILL.md", status="dropped")
    assert fx.status().drift is True


def test_second_generation_compares_against_newest_baseline(fx):
    old_fill_text = SKILL_TEXT + "Restored.\n"
    fx.write_skill(old_fill_text)
    commit = fx.commit("fill")
    fx.fill("fill-g1-001", commit, path="SKILL.md")
    fx.manifest["generations"].append({"index": 2, "gen": "g2", "date": "2026-11-30"})
    fx.manifest["skills"][SKILL]["baselines"].append(
        entry("g2", old_fill_text, STEP_TEXT)
    )
    status = fx.status()
    assert status.baseline["gen"] == "g2"
    assert status.drift is False
    assert status.changes == []
    assert fx.manifest["skills"][SKILL]["baselines"][0]["gen"] == "g1"


def test_second_generation_ignores_older_generation_fills(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    commit = fx.commit("fill")
    fx.fill("fill-g1-001", commit, path="SKILL.md")
    fx.manifest["skills"][SKILL]["baselines"].append(entry("g2", SKILL_TEXT, STEP_TEXT))
    assert fx.status().drift is True


def test_find_manifest_picks_highest_generation_index(tmp_path):
    for name, index in [("orig", 1), ("orig-r2", 2), ("slim", 3), ("zz-broken", None)]:
        folder = tmp_path / name
        folder.mkdir()
        generations = [] if index is None else [{"index": index, "gen": name}]
        (folder / "MANIFEST.json").write_text(json.dumps({"generations": generations}))
    assert baseline_cmd.find_manifest(tmp_path).parent.name == "slim"
    (tmp_path / "slim" / "MANIFEST.json").write_text("not json")
    assert baseline_cmd.find_manifest(tmp_path).parent.name == "orig-r2"


def test_find_manifest_prefers_direct_manifest(tmp_path):
    (tmp_path / "later").mkdir()
    (tmp_path / "later" / "MANIFEST.json").write_text("{}")
    (tmp_path / "MANIFEST.json").write_text("{}")
    assert baseline_cmd.find_manifest(tmp_path) == tmp_path / "MANIFEST.json"


def test_changed_refs_reports_added_and_removed():
    assert changed_refs({"a": "1", "b": "2"}, {"b": "3", "c": "4"}) == {
        "a": "removed",
        "b": "changed",
        "c": "added",
    }


def test_diff_size_counts_lines_and_tokens():
    size = diff_size("a\nb\n", "a\nc\nd\n", len)
    assert size == {"lines_added": 2, "lines_removed": 1, "tokens": 2}


def test_diff_uses_slim_copy(fx):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    commit = fx.commit("fill")
    fx.fill("fill-g1-001", commit, path="SKILL.md")
    slim = fx.baselines / "slim" / SKILL
    slim.mkdir(parents=True)
    (slim / "SKILL.md").write_text(SKILL_TEXT)
    assert fx.status().diff["lines_added"] == 1


def test_tag_commit_resolves_existing_tag(fx):
    git(fx.repo, "tag", "-a", "skills-slim-g1", "-m", "t")
    assert baseline_cmd.tag_commit(fx.repo, "skills-slim-g1") == git(
        fx.repo, "rev-parse", "HEAD"
    )
    assert baseline_cmd.tag_commit(fx.repo, "missing") is None


def test_cli_requires_baselines_option(capsys):
    assert run(["baseline", "status"]) == 2
    assert "--baselines" in capsys.readouterr().err


def test_cli_json_reports_drift_and_never_writes(fx, monkeypatch, capsys):
    fx.write_skill(SKILL_TEXT + "Restored.\n")
    fx.commit("unrecorded")
    fx.status()
    before = sorted(p.name for p in fx.baselines.iterdir())
    monkeypatch.setattr(baseline_cmd, "provider_packages", lambda: [fx.pkg])
    code = run(
        [
            "baseline",
            "status",
            SKILL,
            "--baselines",
            str(fx.baselines),
            "--repo",
            str(fx.repo),
            "--json",
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data[0]["skill"] == SKILL
    assert data[0]["drift"] is True
    assert sorted(p.name for p in fx.baselines.iterdir()) == before


def test_cli_unknown_skill_exits_2(fx, monkeypatch, capsys):
    fx.status()
    monkeypatch.setattr(baseline_cmd, "provider_packages", lambda: [fx.pkg])
    assert run(["baseline", "status", "nope", "--baselines", str(fx.baselines)]) == 2
    assert "valid skills: demo" in capsys.readouterr().err
