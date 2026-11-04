from __future__ import annotations

import hashlib

import pytest
from varde_learn.knowledge.bundle import is_artifact_dir, is_reserved
from varde_learn.knowledge.concept import (
    Concept,
    ConceptMetadataError,
    slug_from_filename,
)
from varde_learn.knowledge.occ import version
from varde_learn.knowledge.walk import WalkError, visit_concepts

from knowledge.helpers import tempdir


def test_concept_metadata_and_filename_slug() -> None:
    concept = Concept.from_bytes(
        b"---\ndescription: useful\naliases: [shortcut]\n---\nbody", "sample"
    )
    concept.validate_new_metadata()
    assert concept.slug == "sample"
    assert slug_from_filename("sample.md") == "sample"
    assert slug_from_filename("sample.MD") is None
    invalid = Concept.from_bytes(b"---\ndescription: '  '\n---\n", "x")
    with pytest.raises(ConceptMetadataError) as error:
        invalid.validate_new_metadata()
    assert error.value.code == "invalid_description"


def test_concept_alias_validation() -> None:
    concept = Concept.from_bytes(
        b"---\ndescription: useful\naliases: shortcut\n---\n", "x"
    )
    with pytest.raises(ConceptMetadataError) as error:
        concept.validate_new_metadata()
    assert error.value.code == "invalid_aliases"


def test_occ_version_is_truncated_sha256() -> None:
    data = b"some file bytes"
    assert version(data) == hashlib.sha256(data).hexdigest()[:16]
    assert version(data) != version(data + b"!")


def test_bundle_predicates() -> None:
    assert all(is_artifact_dir(name) for name in ("target", "node_modules"))
    assert not is_artifact_dir("targets")
    assert all(is_reserved(name) for name in ("index.md", "log.md", "README.md"))
    assert not is_reserved("readme.md")


def test_walk_skips_bookkeeping_hidden_artifact_and_symlinks() -> None:
    root = tempdir("walk")
    (root / "nested").mkdir()
    (root / "target").mkdir()
    (root / ".hidden").mkdir()
    (root / "nested" / "good.md").write_text(
        "---\ntype: note\n---\nbody", encoding="utf-8"
    )
    (root / "index.md").write_text("bad", encoding="utf-8")
    (root / "README.md").write_text("bad", encoding="utf-8")
    (root / "target" / "artifact.md").write_text("bad", encoding="utf-8")
    (root / ".hidden" / "hidden.md").write_text("bad", encoding="utf-8")
    (root / "linked.md").symlink_to(root / "nested" / "good.md")
    found = []
    visit_concepts(root, is_reserved, found.append)
    assert [(item.path.name, item.body) for item in found] == [("good.md", "body")]


def test_walk_aborts_on_invalid_concept() -> None:
    root = tempdir("walk-invalid")
    (root / "bad.md").write_text("not frontmatter", encoding="utf-8")
    with pytest.raises(WalkError) as error:
        visit_concepts(root, is_reserved, lambda _item: None)
    assert error.value.kind == "invalid_concept"
    assert error.value.path == root / "bad.md"
