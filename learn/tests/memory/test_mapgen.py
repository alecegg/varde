from typing import Any

import pytest
from varde_learn.memory.entry import Entry, EntryError
from varde_learn.memory.mapgen import build_map

KEY = "repo-0123456789abcdef"


def make(entry_id: str, **overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": "global",
        "scope_key": "",
        "text": f"summary {entry_id}\nbody",
        "source": "t",
        "created": "c",
    }
    base.update(overrides)
    return Entry(**base)


ENTRIES = [
    make("b", type="pattern"),
    make("a", type="decision", title="Alpha"),
    make("p", scope="project", scope_key=KEY, type="decision"),
]


def test_build_map_groups_by_scope_and_type_deterministically(tmp_path) -> None:
    text = build_map(tmp_path, ENTRIES)
    assert text == build_map(tmp_path, list(reversed(ENTRIES)))
    assert text.index("## project") < text.index("## global")
    assert "- [Alpha](global/a.md) - summary a" in text
    assert text.index("### decision") < text.index("### pattern")
    assert not list(tmp_path.iterdir())


def test_build_map_writes_only_to_destination_with_relative_links(tmp_path) -> None:
    root = tmp_path / "mem"
    root.mkdir()
    out = tmp_path / "out" / "map.md"
    text = build_map(root, ENTRIES, out)
    assert out.read_text(encoding="utf-8") == text
    assert "(../mem/global/a.md)" in text


def test_build_map_refuses_destination_inside_bundle(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with pytest.raises(EntryError):
        build_map(tmp_path, ENTRIES, bundle / "index.md", bundles=[bundle])
    assert not (bundle / "index.md").exists()
