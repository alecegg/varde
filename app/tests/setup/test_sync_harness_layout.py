from pathlib import Path

import pytest
from varde.setup.sync.harness import HarnessId, _layout, detect


@pytest.mark.parametrize("xdg_set", [False, True])
def test_opencode_layout_and_detection_follow_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xdg_set: bool
) -> None:
    home = tmp_path / "home"
    config = tmp_path / "xdg-config" if xdg_set else home / ".config"
    if xdg_set:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    else:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    opencode = config / "opencode"
    opencode.mkdir(parents=True)

    layout = _layout(HarnessId.OPENCODE, home, None)
    assert layout.skills_dir == opencode / "skills"
    assert layout.agents_dir == opencode / "agents"
    assert any(item.id is HarnessId.OPENCODE for item in detect(home))
