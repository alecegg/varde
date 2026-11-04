from pathlib import Path

from varde_data.config import load_data_config


def test_mirror_backends_are_valid_in_config(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "data.toml").write_text(
        '[domains]\nmessages = "mirror-files"\n', encoding="utf-8"
    )
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "mirror-sqlite")
    assert load_data_config(tmp_path).backends["messages"] == "mirror-sqlite"
