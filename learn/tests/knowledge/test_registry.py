from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.knowledge.maps import MapError, generate
from varde_learn.knowledge.registry import RegistryError, search


def _write(path: Path, frontmatter: str, body: str = "body\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")


def test_registry_filters_exact_fields_and_merges_bundles(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    _write(
        first / "nested" / "shared.md",
        (
            "type: decision\nstatus: deprecated\ntags: [rust, cli]\n"
            "priority: 42\norigin: first\n"
        ),
    )
    _write(first / "untyped.md", "title: Untyped\n")
    _write(
        second / "nested" / "shared.md",
        (
            "type: decision\nstatus: deprecated\ntags: [rust, cli]\n"
            "priority: 42\norigin: second\n"
        ),
    )
    _write(second / "other.md", "type: pattern\nstatus: draft\nverified: true\n")

    results = search([first, second], [("tags", "rust"), ("priority", "42")])

    assert [entry.slug for entry in results] == ["nested/shared"]
    assert results[0].type_ == "decision"
    assert results[0].frontmatter["origin"] == "second"
    assert [entry.slug for entry in search([second], [("verified", "true")])] == [
        "other"
    ]
    assert [entry.slug for entry in search([first], [])] == ["nested/shared", "untyped"]
    assert search([first], [("status", "deprecated"), ("type", "pattern")]) == []


def test_registry_skips_reserved_hidden_and_artifact_entries(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "type: note\n")
    _write(tmp_path / "index.md", "type: note\n")
    _write(tmp_path / "README.md", "type: note\n")
    _write(tmp_path / ".hidden" / "hidden.md", "type: note\n")
    _write(tmp_path / "target" / "generated.md", "type: note\n")
    _write(tmp_path / "node_modules" / "generated.md", "type: note\n")

    assert [entry.slug for entry in search([tmp_path], [])] == ["doc"]


def test_registry_reports_invalid_concept_and_missing_bundle(tmp_path: Path) -> None:
    _write(tmp_path / "bad.md", ": not yaml :\n")
    with pytest.raises(RegistryError) as invalid:
        search([tmp_path], [])
    assert invalid.value.kind == "invalid_concept"

    with pytest.raises(RegistryError) as missing:
        search([tmp_path / "missing"], [])
    assert missing.value.kind == "read_dir_failed"


def test_maps_are_deterministic_and_preserve_root_frontmatter(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_text(
        "---\nschema_version: 1\n---\n", encoding="utf-8"
    )
    _write(
        tmp_path / "decision" / "zeta.md",
        "type: decision\ntitle: Zeta\nstatus: deprecated\naliases: [old]\n",
    )
    _write(
        tmp_path / "decision" / "alpha.md",
        "type: decision\ntitle: Alpha\ndescription: New\n",
    )
    _write(tmp_path / "pattern" / "rule.md", "type: pattern\ndescription: Rule\n")

    result = generate(tmp_path)

    assert result.root == "index.md"
    assert result.type_maps == ["decision/index.md", "pattern/index.md"]
    assert result.entries == 3
    root = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "schema_version: 1" in root
    assert "## Active\n\n### decision\n\n- [Alpha](decision/alpha.md)" in root
    assert "## Deprecated\n\n### decision\n\n- [Zeta](decision/zeta.md)" in root
    assert "Description: New" in root
    assert "Description: (no description)" in root
    assert "Aliases: old" in root
    before = root
    generate(tmp_path)
    assert (tmp_path / "index.md").read_text(encoding="utf-8") == before
    assert "[Alpha](alpha.md)" in (tmp_path / "decision" / "index.md").read_text(
        encoding="utf-8"
    )


def test_maps_handle_missing_optional_fields_and_invalid_existing_root(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "legacy.md", "type: reference\n")
    (tmp_path / "index.md").write_text("invalid root map", encoding="utf-8")

    generate(tmp_path)

    root = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "Description: (no description)" in root
    assert "Aliases: none" in root
    assert "Status: active" in root
    assert "[Legacy](legacy.md)" in root


def test_maps_raise_typed_walk_error(tmp_path: Path) -> None:
    _write(tmp_path / "bad.md", ": not yaml :\n")

    with pytest.raises(MapError) as error:
        generate(tmp_path)

    assert error.value.kind == "walk"
