from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_workflow import cli
from varde_workflow.commands import execution_wave as execution_wave_command
from varde_workflow.execution_wave import WaveError, execution_wave
from varde_workflow.execution_wave_paths import (
    canonical_declaration,
    canonical_path,
    declarations_overlap,
    matches_declaration,
    matching_paths,
)
from varde_workflow.task_ownership import OwnershipDeclarations, check, resolve


def test_glob_intersection_and_matching() -> None:
    assert matches_declaration("src/**/*.py", "src/a/b.py")
    assert not matches_declaration("src/*.py", "src/a/b.py")
    assert declarations_overlap("src/*.py", "src/a.py")
    assert declarations_overlap("src/**", "src/a/b.py")
    assert not declarations_overlap("src/a*", "src/b*")


def test_matching_paths_resolves_ignored_and_visible_prefixes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    ignored = root / "ignored" / "nested"
    visible = root / "visible"
    ignored.mkdir(parents=True)
    visible.mkdir()
    (root / ".gitignore").write_text("ignored/\n")
    (ignored / "owned.py").touch()
    (visible / "owned.py").touch()
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    assert matching_paths(root, "visible/*.py") == ["visible/owned.py"]
    assert matching_paths(root, "ignored/**/*.py") == ["ignored/nested/owned.py"]


def test_matching_paths_includes_ignored_outputs_and_dangling_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "dist").mkdir(parents=True)
    (root / "static" / "ui").mkdir(parents=True)
    (root / "links").mkdir()
    (root / ".gitignore").write_text("dist/\nstatic/ui/\n")
    (root / "dist" / "bundle.js").touch()
    (root / "static" / "ui" / "app.js").touch()
    (root / "links" / "broken.py").symlink_to("missing.py")
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    assert matching_paths(root, "dist/**") == ["dist", "dist/bundle.js"]
    assert matching_paths(root, "static/ui/**") == ["static/ui", "static/ui/app.js"]
    assert matching_paths(root, "links/*.py") == ["links/broken.py"]


def test_root_globs_prune_large_dependency_directories(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / "node_modules" / "package").mkdir(parents=True)
    (root / "app.py").touch()
    (root / ".venv" / "lib" / "hidden.py").touch()
    (root / "node_modules" / "package" / "hidden.py").touch()

    assert matching_paths(root, "**/*.py") == ["app.py"]


def test_nested_globs_prune_dependency_directories_but_explicit_prefix_walks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src" / "node_modules").mkdir(parents=True)
    (root / "src" / "a.py").touch()
    (root / "src" / "node_modules" / "hidden.py").touch()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg.py").touch()

    assert matching_paths(root, "src/**/*.py") == ["src/a.py"]
    assert matching_paths(root, "node_modules/*.py") == ["node_modules/pkg.py"]


def test_root_glob_overlaps_non_root_path() -> None:
    assert canonical_declaration(Path("/nonexistent-root"), "**") == "**"
    assert canonical_declaration(Path("/nonexistent-root"), "*.py") == "*.py"
    assert declarations_overlap("**", "src/a.py")
    assert declarations_overlap("**", "src/")
    assert not declarations_overlap("*.py", "src/a.py")


def test_canonical_paths_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "real").mkdir()
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    assert canonical_path(root, "link/new.py") == "real/new.py"
    assert canonical_declaration(root, "link/*.py") == "real/*.py"
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes repository"):
        canonical_path(root, "escape/new.py")


def test_canonical_path_resolves_dangling_and_parent_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src" / "deep").mkdir(parents=True)
    (root / "alias").symlink_to("src/future", target_is_directory=True)
    (root / "parent").symlink_to("src/deep", target_is_directory=True)
    assert canonical_path(root, "alias/new.rs") == "src/future/new.rs"
    assert canonical_path(root, "parent/../new.rs") == "src/new.rs"
    assert canonical_path(root, "./src/../src/new.rs") == "src/new.rs"


def test_canonical_path_rejects_symlink_loops_under_missing_prefixes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "loop").symlink_to("loop")
    (root / "hidden").symlink_to("missing/../loop/../real")
    for path in ("missing/../loop/new.rs", "hidden/new.rs"):
        with pytest.raises(OSError, match="symbolic links"):
            canonical_path(root, path)


def test_ownership_resolution_validates_missing_and_excluded_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "present.py").touch()
    decls = OwnershipDeclarations(owned={"missing.py"}, owns={"new.py"})
    resolution = resolve(root, decls, [], None, set())
    assert resolution.blockers == ["missing.py: path does not exist"]
    resolution = resolve(
        root, OwnershipDeclarations(owns={"present.py"}), ["present.py"], None, set()
    )
    assert "present.py: overlaps excluded path present.py" in resolution.blockers


def _task(path: Path, owns: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nstatus: todo\ndepends_on: []\nowns: [{owns}]\n---\n")


class Impact:
    def dependents(self, repo_root: Path, file: Path) -> list[Path] | None:
        return [Path("src/beta.py")] if file.name == "alpha.py" else []


def test_independent_tasks_form_wave_and_dependents_block_conflicting_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    plan = root / "plan"
    (plan / "tasks").mkdir(parents=True)
    (root / "src").mkdir()
    for name in ("alpha.py", "beta.py", "gamma.py"):
        (root / "src" / name).touch()
    _task(plan / "tasks" / "alpha.md", "src/alpha.py")
    _task(plan / "tasks" / "beta.md", "src/beta.py")
    _task(plan / "tasks" / "gamma.md", "src/gamma.py")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    data = execution_wave(plan, root, 3, Impact())
    assert data["ready"] == ["alpha", "beta", "gamma"]
    assert data["next_wave"] == ["alpha", "gamma"]


def test_missing_impact_is_only_reported_when_tasks_need_comparison(
    tmp_path: Path,
) -> None:
    root, plan = tmp_path / "repo", tmp_path / "repo" / "plan"
    (plan / "tasks").mkdir(parents=True)
    _task(plan / "tasks" / "alpha.md", "src/a")
    data = execution_wave(plan, root, 3)
    assert data["next_wave"] == ["alpha"]
    assert not any("varde map unavailable" in reason for reason in data["reasons"])
    _task(plan / "tasks" / "beta.md", "src/b")
    data = execution_wave(plan, root, 3)
    assert any("varde map unavailable" in reason for reason in data["reasons"])
    (plan / "tasks" / "alpha.md").write_text(
        "---\nstatus: todo\ndepends_on: [beta]\nowns: [src/a]\n---\n"
    )
    _task(plan / "tasks" / "beta.md", "src/b")
    (plan / "tasks" / "beta.md").write_text(
        "---\nstatus: todo\ndepends_on: [alpha]\nowns: [src/b]\n---\n"
    )
    with pytest.raises(WaveError, match="cycle"):
        execution_wave(plan, root, 1)


def test_ownership_audit_reports_stray_changed_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    task = root / "plan" / "tasks" / "task.md"
    _task(task, "src/owned.py")
    (root / "src").mkdir()
    (root / "src" / "owned.py").write_text("ok")
    (root / "stray.py").write_text("stray")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
    (root / "src" / "owned.py").write_text("changed")
    (root / "stray.py").write_text("changed")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "change"], check=True)
    audit = check(task, "HEAD", root, [])
    assert audit.status == "stray"
    assert audit.stray == ["stray.py"]


class NoDependents:
    def dependents(self, repo_root: Path, file: Path) -> list[Path]:
        return []


def test_execution_wave_uses_configured_builders_when_omitted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir = Path(os.environ["VARDE_CONFIG_DIR"])
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text("[orchestration]\nbuilders = 2\n")
    root = tmp_path / "repo"
    root.mkdir()
    plan = root / "plan"
    (plan / "tasks").mkdir(parents=True)
    for name in ("alpha", "beta", "gamma"):
        _task(plan / "tasks" / f"{name}.md", f"src/{name}.py")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )

    assert (
        cli.run(
            [
                "plan",
                "execution-wave",
                str(plan),
                "--repo-root",
                str(root),
                "--json",
            ],
            io=SimpleNamespace(impact=NoDependents()),
        )
        == 0
    )
    data = json.loads(capsys.readouterr().out)["data"]
    assert len(data["next_wave"]) == 2
    assert data["reasons"] == []


def test_execution_wave_invalid_input_uses_error_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = SimpleNamespace(
        plan_dir=str(tmp_path / "missing"),
        repo_root=str(tmp_path),
        max_workers=1,
        json=True,
    )
    assert execution_wave_command.run(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert '"code":"invalid_input"' in captured.err
    assert '"outcome":"tool-error"' in captured.err


def test_trailing_slash_declaration_is_prefix_match() -> None:
    assert matches_declaration("a/b/", "a/b/c/d.py")
    assert matches_declaration("a/b/", "a/b")
    assert not matches_declaration("a/b/", "a/bc/d.py")
    assert matches_declaration("a/*/", "a/x/y.py")
    assert matches_declaration("a/b.py", "a/b.py")
    assert not matches_declaration("a/b", "a/b/c.py")


def test_resolve_treats_bare_existing_directory_as_prefix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "c.py").touch()
    (root / "a" / "file.py").touch()
    resolution = resolve(
        root, OwnershipDeclarations(owns={"a/b", "a/file.py"}), [], None, set()
    )
    assert resolution.owns_path("a/b/c.py")
    assert resolution.owns_path("a/file.py")
    assert not resolution.owns_path("a/file.py/x")


def test_directory_and_nested_file_overlap_in_wave_scheduler(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    plan = root / "plan"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "c.py").touch()
    _task(plan / "tasks" / "dir.md", "a/b/")
    _task(plan / "tasks" / "file.md", "a/b/c.py")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@e.com", "-c", "user.name=T"]
        + ["commit", "-qm", "init"],
        check=True,
    )
    data = execution_wave(plan, root, 2, Impact())
    assert data["ready"] == ["dir", "file"]
    assert len(data["next_wave"]) == 1
