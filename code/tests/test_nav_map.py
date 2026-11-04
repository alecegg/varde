from __future__ import annotations

from varde_code.query.nav_map import format_map


def test_format_map_renders_module_layer_edges():
    data = {
        "module_layers": {
            "edges": [{"from_module": "a", "to_module": "b", "crossing_files": 3}],
            "cycles": [],
        }
    }
    assert "- a → b (3 files)" in format_map(data)


def test_nav_map_text_points_at_resolved_knowledge_dir(monkeypatch, tmp_path) -> None:
    from varde_code.query.nav_map import nav_map_text

    root = tmp_path / "repo"
    notes = tmp_path / "notes"
    (root / ".git").mkdir(parents=True)
    notes.mkdir()
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "config.toml").write_text(f'[project."{root}"]\nknowledge = "{notes}"\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_CODE_TOZ", "0")
    monkeypatch.delenv("VARDE_KNOWLEDGE_DIR", raising=False)
    text = nav_map_text(
        {
            "entrypoints": [],
            "subsystems": [],
            "flows": [],
            "hotspots": [],
            "repoRoot": str(root),
        },
        True,
    )
    assert text.startswith(f"Project knowledge: {notes.resolve()}/")
    assert "memory-bank" not in text
