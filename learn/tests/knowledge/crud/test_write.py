from pathlib import Path

import pytest
from varde_learn.knowledge.crud.delete import DeleteError, delete
from varde_learn.knowledge.crud.timestamps import git_created_updated
from varde_learn.knowledge.crud.update import UpdateError, update
from varde_learn.knowledge.occ import version

DOC = b"---\ntype: decision\ndescription: A useful decision.\n---\n# Body\n"
DOC2 = b"---\ntype: decision\ndescription: Updated.\n---\n# New body\n"


def test_update_replaces_document_and_reports_versions(tmp_path: Path) -> None:
    path = tmp_path / "decision.md"
    path.write_bytes(DOC)

    result = update(tmp_path, "decision", version(DOC), DOC2)

    assert result.slug == "decision"
    assert result.old_version == version(DOC)
    assert result.new_version == version(DOC2)
    assert path.read_bytes() == DOC2


def test_update_rejects_stale_version_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "decision.md"
    path.write_bytes(DOC)

    with pytest.raises(UpdateError) as error:
        update(tmp_path, "decision", "deadbeef", DOC2)

    assert error.value.kind == "conflict"
    assert path.read_bytes() == DOC


def test_update_rejects_invalid_document_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "decision.md"
    path.write_bytes(DOC)

    with pytest.raises(UpdateError) as error:
        update(tmp_path, "decision", version(DOC), b"not frontmatter")

    assert error.value.kind == "invalid_concept"
    assert path.read_bytes() == DOC


def test_update_accepts_concept_without_type(tmp_path: Path) -> None:
    before = b"---\ndescription: A note.\n---\nbody\n"
    after = b"---\ndescription: Revised note.\n---\nnew body\n"
    (tmp_path / "note.md").write_bytes(before)

    result = update(tmp_path, "note", version(before), after)

    assert result.new_version == version(after)
    assert (tmp_path / "note.md").read_bytes() == after


def test_update_missing_file_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(UpdateError) as error:
        update(tmp_path, "missing", "00000000", DOC)
    assert error.value.kind == "not_found"


def test_update_nested_slug(tmp_path: Path) -> None:
    nested = tmp_path / "pattern"
    nested.mkdir()
    (nested / "decision.md").write_bytes(DOC)

    result = update(tmp_path, "pattern/decision", version(DOC), DOC2)
    assert result.slug == "pattern/decision"


def test_delete_removes_file_and_returns_slug(tmp_path: Path) -> None:
    path = tmp_path / "decision.md"
    path.write_bytes(DOC)
    assert delete(tmp_path, "decision") == "decision"
    assert not path.exists()


def test_delete_missing_file_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(DeleteError) as error:
        delete(tmp_path, "missing")
    assert error.value.kind == "not_found"


def test_delete_rejects_invalid_slug(tmp_path: Path) -> None:
    with pytest.raises(DeleteError) as error:
        delete(tmp_path, "../outside")
    assert error.value.kind == "invalid_slug"


def test_delete_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    victim = outside / "victim.md"
    victim.write_bytes(DOC)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(DeleteError) as error:
            delete(tmp_path, "linked/victim")
        assert error.value.kind == "invalid_slug"
        assert victim.read_bytes() == DOC
    finally:
        victim.unlink(missing_ok=True)
        outside.rmdir()


def test_timestamps_are_best_effort_for_non_git_bundle(tmp_path: Path) -> None:
    (tmp_path / "decision.md").write_bytes(DOC)
    assert git_created_updated(tmp_path, "decision") == (None, None)


def test_timestamps_reject_invalid_slug_without_git(tmp_path: Path) -> None:
    assert git_created_updated(tmp_path, "../outside") == (None, None)
