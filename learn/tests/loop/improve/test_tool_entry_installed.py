from pathlib import Path

import pytest
from varde_learn.loop.improve import tool_entry


@pytest.fixture(autouse=True)
def config(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(tool_entry.memory_dirs, "load_config_document", lambda: state)
    return state


def _install(sync: Path, skill: str, code: str) -> Path:
    root = sync / skill
    (root / "step_tools" / skill).mkdir(parents=True)
    (root / ".varde-managed-skill").write_text("varde-managed-skill\n")
    (root / "step_tools" / skill / "go.py").write_text(code)
    (root / "step_tools" / "registry.toml").write_text(
        f'[[tool]]\nskill = "{skill}"\nstep = "go"\nentry = "{skill}/go.py"\n'
    )
    return root


def test_no_saved_target_gives_no_roots(config):
    assert tool_entry.sync_target() is None
    assert tool_entry.installed_roots() == []


def test_missing_target_dir_gives_none(config, tmp_path):
    config["sync"] = {"skills_dir": str(tmp_path / "absent")}
    assert tool_entry.sync_target() is None
    config["sync"] = {"skills_dir": 3}
    assert tool_entry.sync_target() is None


def test_sync_skill_roots_need_sidecar(tmp_path):
    root = _install(tmp_path, "varde-x", "def run(a): return 0\n")
    (tmp_path / "plain").mkdir()
    assert tool_entry.sync_skill_roots(tmp_path) == [root]


def test_installed_tool_wins_over_package(config, tmp_path, monkeypatch):
    sync = tmp_path / "sync"
    root = _install(sync, "varde-x", "def run(a): return 7\n")
    package = tmp_path / "pkg"
    _install(package.parent / "pkgroot", "varde-x", "def run(a): return 3\n")
    pkg_root = package.parent / "pkgroot" / "varde-x"
    config["sync"] = {"skills_dir": str(sync)}
    monkeypatch.setattr(tool_entry, "package_roots", lambda: [pkg_root])
    monkeypatch.setattr(tool_entry.calls, "append_tool_call", lambda *a, **k: None)
    roots = tool_entry.module_roots()
    assert roots[0] == root
    assert tool_entry.run_counted("varde-x", "go", [], roots) == 7
    assert len(tool_entry.all_rows(roots)) == 1


def test_package_fallback_when_skill_not_installed(config, tmp_path, monkeypatch):
    sync = tmp_path / "sync"
    sync.mkdir()
    pkg_root = _install(tmp_path / "pkgroot", "varde-x", "def run(a): return 3\n")
    config["sync"] = {"skills_dir": str(sync)}
    monkeypatch.setattr(tool_entry, "package_roots", lambda: [pkg_root])
    monkeypatch.setattr(tool_entry.calls, "append_tool_call", lambda *a, **k: None)
    assert tool_entry.run_counted("varde-x", "go", [], tool_entry.module_roots()) == 3
