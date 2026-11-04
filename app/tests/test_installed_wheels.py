from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
import time
import tomllib
import zipfile
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
PRESETS = {
    "toz": {"varde-toz", "varde-manage"},
    "code": {"varde-code", "varde-scan", "varde-customize", "varde-manage"},
    "learn": {
        "varde-learn",
        "varde-knowledge",
        "varde-docs",
        "varde-diagnose",
        "varde-improve",
        "varde-session-notes",
        "varde-skill-authoring",
        "varde-doc-authoring",
        "varde-manage",
    },
    "dev": {
        "varde-explore",
        "varde-explain",
        "varde-pr",
        "varde-prototype",
        "varde-manage",
    },
    "visualize": {"varde-visualize", "varde-manage"},
    "design": {"varde-design", "varde-manage"},
    "workflow": {
        "varde-plan",
        "varde-build",
        "varde-orchestrate",
        "varde-swarm",
        "varde-review",
        "varde-review-ui",
        "varde-verify",
        "varde-explore",
        "varde-explain",
        "varde-pr",
        "varde-knowledge",
        "varde-learn",
        "varde-docs",
        "varde-prototype",
        "varde-visualize",
        "varde-diagnose",
        "varde-improve",
        "varde-session-notes",
        "varde-skill-authoring",
        "varde-doc-authoring",
        "varde-code",
        "varde-customize",
        "varde-scan",
        "varde-toz",
        "varde-manage",
    },
    "full": {
        "varde-diagnose",
        "varde-improve",
        "varde-session-notes",
        "varde-skill-authoring",
        "varde-doc-authoring",
        "varde-docs",
        "varde-plan",
        "varde-build",
        "varde-orchestrate",
        "varde-swarm",
        "varde-code",
        "varde-customize",
        "varde-explore",
        "varde-explain",
        "varde-pr",
        "varde-knowledge",
        "varde-learn",
        "varde-manage",
        "varde-prototype",
        "varde-visualize",
        "varde-design",
        "varde-review",
        "varde-review-ui",
        "varde-verify",
        "varde-scan",
        "varde-toz",
    },
}
WHEEL_SKILLS = {
    "varde-toz": {"varde-toz"},
    "varde-code": {"varde-code", "varde-scan", "varde-customize"},
    "varde-learn": {
        "varde-learn",
        "varde-knowledge",
        "varde-docs",
        "varde-diagnose",
        "varde-improve",
        "varde-session-notes",
        "varde-skill-authoring",
        "varde-doc-authoring",
    },
    "varde-workflow": {
        "varde-plan",
        "varde-build",
        "varde-orchestrate",
        "varde-swarm",
        "varde-review",
        "varde-review-ui",
        "varde-verify",
    },
    "varde-dev": {
        "varde-explore",
        "varde-explain",
        "varde-pr",
        "varde-prototype",
    },
    "varde-visualize": {"varde-visualize"},
    "varde-design": {"varde-design"},
    "varde": {"varde-manage"},
}
WORKFLOW_AGENTS = {
    "accessibility",
    "readability",
    "spec-adherence",
    "ux-advocate",
    "varde-planner",
    "varde-builder",
    "varde-reviewer",
    "varde-explorer",
}
PROVIDER_GROUPS = {"varde.modules", "varde.skills", "varde.agents"}


def missing_provider_dependencies(
    providers: list[tuple[str, str]], requirements: list[str]
) -> set[str]:
    dependency_names = {
        canonicalize_name(Requirement(item).name) for item in requirements
    }
    return {
        distribution
        for group, distribution in providers
        if group in PROVIDER_GROUPS
        and canonicalize_name(distribution) != "varde"
        and canonicalize_name(distribution) not in dependency_names
    }


def test_missing_provider_dependency_names_the_distribution() -> None:
    assert missing_provider_dependencies(
        [("varde.skills", "not-a-dependency"), ("other", "ignored")],
        ["varde-core>=1"],
    ) == {"not-a-dependency"}


@pytest.fixture(scope="module")
def installed_workspace(tmp_path_factory: pytest.TempPathFactory):
    started = time.monotonic()
    root = tmp_path_factory.mktemp("installed-wheels")
    wheelhouse = root / "w"
    wheelhouse.mkdir()
    subprocess.run(
        ["uv", "build", "--all-packages", "--wheel", "--out-dir", str(wheelhouse)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(wheelhouse.glob("*.whl"))
    assert wheels
    venv = root / "venv"
    subprocess.run(
        ["uv", "venv", str(venv)], check=True, capture_output=True, text=True
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            *(str(wheel) for wheel in wheels),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    executable = venv / ("Scripts/varde.exe" if os.name == "nt" else "bin/varde")
    env = os.environ.copy()
    env["HOME"] = str(root)
    env["XDG_CONFIG_HOME"] = str(root / "xdg")
    env["XDG_DATA_HOME"] = str(root / "xdgdata")
    env["XDG_CACHE_HOME"] = str(root / "home/.cache")
    env["VARDE_CONFIG_DIR"] = str(root / "cfg")
    home_config = Path(env["HOME"]) / ".config/varde/config.toml"
    xdg_config = Path(env["XDG_CONFIG_HOME"]) / "varde/config.toml"
    for canary in (home_config, xdg_config):
        canary.parent.mkdir(parents=True, exist_ok=True)
        canary.write_bytes(b"leave this file alone")
    yield {
        "root": root,
        "wheelhouse": wheelhouse,
        "python": python,
        "varde": executable,
        "env": env,
        "canaries": (home_config, xdg_config),
    }
    print(f"installed wheel fixture runtime: {time.monotonic() - started:.1f}s")


@pytest.mark.parametrize("preset,expected", PRESETS.items())
def test_installed_cli_syncs_each_preset(installed_workspace, preset, expected) -> None:
    root = installed_workspace["root"] / preset
    skills = root / "skills"
    agents = root / "agents"
    config_file = Path(installed_workspace["env"]["VARDE_CONFIG_DIR"]) / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    original_config = b"[unrelated]\nvalue = 1\n"
    config_file.write_bytes(original_config)
    result = subprocess.run(
        [
            str(installed_workspace["varde"]),
            "setup",
            "sync",
            "--skills-dir",
            str(skills),
            "--agents-dir",
            str(agents),
            "--harnesses",
            "claude",
            "--link-mode",
            "copy",
            "--preset",
            preset,
            "--json",
        ],
        env=installed_workspace["env"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    config_file = Path(installed_workspace["env"]["VARDE_CONFIG_DIR"]) / "config.toml"
    assert config_file.is_file()
    assert config_file.is_relative_to(installed_workspace["root"])
    for canary in installed_workspace["canaries"]:
        assert canary.read_bytes() == b"leave this file alone"
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["ok"] is True
    assert report["meta"]["dry_run"] is False
    # This test supplies the file so it can verify sync left it unchanged.
    assert config_file.read_bytes() == original_config
    assert "sync" not in tomllib.loads(config_file.read_text())
    assert set(report["data"]) == {"moved", "skipped", "unrewritable", "would"}
    installed = {path.name for path in skills.glob("varde-*") if path.is_dir()}
    assert installed == expected
    for skill in expected:
        assert (skills / skill / "SKILL.md").is_file()
    if preset == "learn":
        assert (
            skills / "varde-knowledge" / "references/varde-workflow-cli.md"
        ).is_file()
    if preset == "workflow":
        assert (skills / "varde-explore" / "references/varde-code-cli.md").is_file()
        for reference in (
            "references/review-gates.md",
            "references/varde-workflow-cli.md",
        ):
            assert (skills / "varde-build" / reference).is_file()
        assert (skills / "varde-plan" / "references/varde-code-cli.md").is_file()
        assert (skills / "varde-review" / "references/varde-code-cli.md").is_file()
        for tier in ("varde-plan", "varde-orchestrate", "varde-swarm"):
            assert (skills / tier / "SKILL.md").is_file()
        assert {path.stem for path in (agents / "claude").glob("varde-*")} == {
            "varde-planner",
            "varde-builder",
            "varde-reviewer",
            "varde-explorer",
        }


def _wheel_skill_names(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    skills = {
        match.group(1)
        for name in names
        if (match := re.search(r"/skills/(varde-[^/]+)/SKILL\.md$", name))
    }
    assert not any("/evals/" in name for name in names)
    return skills


def _wheel_agent_names(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    variants = ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md")
    return {
        name.split("/agents/", 1)[1].split("/", 1)[0]
        for name in names
        if "/agents/" in name and name.rsplit("/", 1)[-1] in variants
    }


def test_wheels_contain_the_expected_skills(installed_workspace) -> None:
    wheels = {
        wheel.name.split("-", 1)[0].replace("_", "-"): wheel
        for wheel in installed_workspace["wheelhouse"].glob("*.whl")
    }
    assert set(WHEEL_SKILLS) <= set(wheels)
    for distribution, expected in WHEEL_SKILLS.items():
        assert _wheel_skill_names(wheels[distribution]) == expected
    assert _wheel_agent_names(wheels["varde-workflow"]) == WORKFLOW_AGENTS
    for wheel in installed_workspace["wheelhouse"].glob("*.whl"):
        distribution = wheel.name.split("-", 1)[0].replace("_", "-")
        if distribution not in WHEEL_SKILLS:
            assert _wheel_skill_names(wheel) == set()


def _source_how_files() -> dict[str, set[str]]:
    """Wheel-relative how files per distribution, from the source tree."""
    found: dict[str, set[str]] = {}
    for how in [*ROOT.glob("*/src/*/how"), *ROOT.glob("*/src/*/agents/*/how")]:
        package = next(p for p in how.parents if p.parent.name == "src")
        project = tomllib.loads((package.parents[1] / "pyproject.toml").read_text())
        name = canonicalize_name(project["project"]["name"])
        pattern = "*/*.md" if how.parent == package else "*.md"
        found.setdefault(name, set()).update(
            path.relative_to(package.parent).as_posix() for path in how.glob(pattern)
        )
    return found


def _how_owner(step: str) -> str:
    """Skill or agent name that owns a wheel-relative how file."""
    parts = Path(step).parts
    return parts[-3] if parts[-2] == "how" else parts[-2]


def test_wheels_contain_their_how_files(installed_workspace) -> None:
    expected = _source_how_files()
    for wheel in installed_workspace["wheelhouse"].glob("*.whl"):
        distribution = canonicalize_name(wheel.name.split("-", 1)[0])
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
        packaged = {name for name in names if "/how/" in name and name.endswith(".md")}
        assert packaged == expected.get(distribution, set()), distribution


def test_code_wheel_contains_baseline_data(installed_workspace) -> None:
    source = ROOT / "code/src/varde_code/quality_score/baseline_data"
    expected = {
        "varde_code/quality_score/baseline_data/" + path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert "varde_code/quality_score/baseline_data/cal-1.toml" in expected
    assert "varde_code/quality_score/baseline_data/corpus.json" in expected
    wheel = next(installed_workspace["wheelhouse"].glob("varde_code-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        packaged = {
            n
            for n in archive.namelist()
            if "/baseline_data/" in n and not n.endswith("/")
        }
    assert packaged == expected


def test_sync_installs_how_files_and_doc_how_lists_topics(installed_workspace) -> None:
    skills = installed_workspace["root"] / "how-skills"
    subprocess.run(
        [
            str(installed_workspace["varde"]),
            "setup",
            "sync",
            "--skills-dir",
            str(skills),
            "--agents-dir",
            str(installed_workspace["root"] / "how-agents"),
            "--harnesses",
            "none",
            "--link-mode",
            "copy",
            "--preset",
            "full",
            "--json",
        ],
        env=installed_workspace["env"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (skills / "varde-docs" / "how").is_dir()
    for steps in _source_how_files().values():
        for skill in {_how_owner(step) for step in steps}:
            expected = {Path(s).stem for s in steps if _how_owner(s) == skill}
            result = subprocess.run(
                [str(installed_workspace["varde"]), "learn", "how", skill],
                env=installed_workspace["env"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            listed = {line.split(" - ", 1)[0] for line in result.stdout.splitlines()}
            assert expected <= listed


def _check_how(repo: Path, baselines: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(ROOT / "core/scripts/check-refs.sh"),
            "--check-how",
            str(repo),
            str(baselines),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _how_fixture(root: Path, *, pointer: str, topics: list[str]) -> None:
    pkg = root / "m/src/pkg"
    skill = pkg / "skills/varde-x"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: varde-x\n---\n{pointer}\n")
    for step in topics:
        topic = pkg / "how/varde-x" / f"{step}.md"
        topic.parent.mkdir(parents=True, exist_ok=True)
        topic.write_text("---\ntopic: varde-x/a\nversion: 1\nsummary: s\n---\nb\n")


def test_check_refs_how_fixtures(tmp_path: Path) -> None:
    baselines = tmp_path / "baselines"
    (baselines / "claude55").mkdir(parents=True)
    log = baselines / "claude55/changelog.jsonl"
    log.write_text('{"status": "retired", "step": "varde-x/old"}\n')
    clean = tmp_path / "clean"
    _how_fixture(clean, pointer="- how: a - do a", topics=["a"])
    assert _check_how(clean, baselines).returncode == 0
    missing = tmp_path / "missing"
    _how_fixture(missing, pointer="- how: a - do a", topics=[])
    assert "no topic file" in _check_how(missing, baselines).stderr
    orphan = tmp_path / "orphan"
    _how_fixture(orphan, pointer="- how: a - do a", topics=["a", "b"])
    assert "orphan" in _check_how(orphan, baselines).stderr
    reused = tmp_path / "reused"
    _how_fixture(reused, pointer="- how: old - do it", topics=["old"])
    assert "retired id" in _check_how(reused, baselines).stderr


def test_sdist_builds_wheel_with_the_same_skills(installed_workspace) -> None:
    for distribution, expected in WHEEL_SKILLS.items():
        sdist_dir = installed_workspace["root"] / f"{distribution}-sdist"
        sdist_dir.mkdir()
        subprocess.run(
            [
                "uv",
                "build",
                "--sdist",
                "--package",
                distribution,
                "--out-dir",
                str(sdist_dir),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        sdist = next(sdist_dir.glob("*.tar.gz"))
        with tarfile.open(sdist) as archive:
            members = archive.getnames()
        assert not any("evals/" in name for name in members)
        rebuilt = installed_workspace["root"] / f"{distribution}-rebuilt"
        rebuilt.mkdir()
        subprocess.run(
            ["uv", "build", str(sdist), "--wheel", "--out-dir", str(rebuilt)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert _wheel_skill_names(next(rebuilt.glob("*.whl"))) == expected


def test_installed_skill_script_keeps_executable_mode(installed_workspace) -> None:
    skills = installed_workspace["root"] / "exec-skills"
    subprocess.run(
        [
            str(installed_workspace["varde"]),
            "setup",
            "sync",
            "--skills-dir",
            str(skills),
            "--agents-dir",
            str(installed_workspace["root"] / "exec-agents"),
            "--harnesses",
            "none",
            "--link-mode",
            "copy",
            "--preset",
            "workflow",
            "--json",
        ],
        env=installed_workspace["env"],
        check=True,
        capture_output=True,
        text=True,
    )
    script = skills / "varde-swarm/scripts/select-plans.py"
    assert script.is_file()
    assert script.stat().st_mode & 0o111


def test_installed_learn_docs_help_succeeds(installed_workspace) -> None:
    result = subprocess.run(
        [str(installed_workspace["varde"]), "learn", "docs", "--help"],
        env=installed_workspace["env"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_provider_distributions_are_dependencies_of_varde(installed_workspace) -> None:
    script = (
        "import importlib.metadata as m, json; "
        "providers=[(e.group, e.dist.metadata['Name']) for g in "
        "('varde.modules','varde.skills','varde.agents') "
        "for e in m.entry_points(group=g)]; "
        "app=m.distribution('varde'); "
        "print(json.dumps({'providers': providers, 'requires': app.requires or []}))"
    )
    result = subprocess.run(
        [str(installed_workspace["python"]), "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    metadata = json.loads(result.stdout)
    missing = missing_provider_dependencies(metadata["providers"], metadata["requires"])
    assert not missing, (
        f"provider distributions missing from varde dependencies: {sorted(missing)}"
    )
