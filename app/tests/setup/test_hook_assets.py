from pathlib import Path

import pytest
from varde.setup.assets.hooks import load_hook_asset
from varde.setup.hooks_install import run


@pytest.mark.parametrize("name", ["opencode.ts", "opencode-v1.ts", "pi.ts"])
def test_hook_asset_names_its_harness(name: str) -> None:
    harness = "pi" if name.startswith("pi") else "opencode"
    assert f"--harness {harness}".encode() in load_hook_asset(name)


def test_unknown_hook_asset_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown hook asset"):
        load_hook_asset("unknown.ts")


@pytest.mark.parametrize(
    "name,harness,version",
    [
        ("opencode.ts", "opencode", "2"),
        ("opencode-v1.ts", "opencode", "1"),
        ("pi.ts", "pi", None),
    ],
)
def test_plugin_install_writes_nonempty_file_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    harness: str,
    version: str | None,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    if version is None:
        monkeypatch.delenv("VARDE_AGENTS_OPENCODE_VERSION", raising=False)
    else:
        monkeypatch.setenv("VARDE_AGENTS_OPENCODE_VERSION", version)
    monkeypatch.setattr("sys.argv", [str(tmp_path / "bin" / "varde")])
    args = ["install", "--harness", harness]
    assert run(args) == 0
    target = (
        home / ".config/opencode/plugin/varde.ts"
        if harness == "opencode"
        else home / ".pi/agent/extensions/varde.ts"
    )
    first = target.read_text()
    assert "--harness" in first
    assert run(args) == 0
    assert target.read_text() == first


@pytest.mark.parametrize(
    ("version", "asset"),
    [
        ("opencode v1.4.2", "opencode-v1.ts"),
        ("opencode v2.0.17", "opencode.ts"),
        ("OpenCode 2.0.18", "opencode.ts"),
        ("opencode v2.0.32", "opencode.ts"),
        ("unknown", "opencode.ts"),
    ],
)
def test_hook_install_selects_asset_and_warns_below_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    version: str,
    asset: str,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "varde.setup.hooks_install.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=version),
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("sys.argv", [str(tmp_path / "bin" / "varde")])
    assert run(["install", "--harness", "opencode"]) == 0
    selected = (home / ".config/opencode/plugin/varde.ts").read_text()
    assert ("opencode 1.x" in selected) is (asset == "opencode-v1.ts")
    warning = capsys.readouterr().out
    assert ("below the supported 2.x baseline 2.0.18" in warning) is (
        version == "opencode v2.0.17"
    )
