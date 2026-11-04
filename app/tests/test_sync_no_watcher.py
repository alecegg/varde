import json
from pathlib import Path

import pytest
from varde.setup.sync.command import run


def _sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.chdir(repo)
    args = ["--skills-dir", str(tmp_path / "s"), "--agents-dir", str(tmp_path / "a")]
    assert (
        run([*args, "--harnesses", "none", "--skills", "varde-build", "--no-packs"])
        == 0
    )


def test_sync_registers_no_watcher_and_writes_nothing_with_no_packs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("sync must not register a watcher")

    monkeypatch.setattr("varde_code.index.supervise.ensure", fail)
    _sync(tmp_path, monkeypatch, repo)

    assert "repo-map" not in capsys.readouterr().out
    assert not (repo / "docs").exists()
    assert not (repo / "AGENTS.md").exists()


def test_impact_query_builds_no_index_in_any_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Impact queries never build an index, in linked or main checkouts."""
    from varde.glue.contracts import _CodeImpact

    built: list[str] = []
    monkeypatch.setattr(
        "varde_code.query.run_mode",
        lambda *_a, **_k: json.dumps(
            {"ok": False, "data": {"error": {"code": "index_missing"}}}
        ),
    )
    monkeypatch.setattr(
        "varde_code.index.build.build", lambda root, *_a: built.append(str(root))
    )
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: elsewhere\n")
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)

    assert _CodeImpact().dependents(linked, linked / "a.py") is None
    assert _CodeImpact().dependents(main, main / "a.py") is None
    assert built == []
