from pathlib import Path

import pytest
from varde_learn.knowledge.crud import (
    ConceptIoError,
    concept_path,
    relative_slug,
    validate_slug,
)
from varde_learn.knowledge.crud.create import CreateError, create
from varde_learn.knowledge.crud.list import ListedConcept
from varde_learn.knowledge.crud.list import list as list_concepts
from varde_learn.knowledge.crud.show import ShowError, show
from varde_learn.knowledge.occ import version

DOC = b"---\ntype: decision\ndescription: A useful decision.\n---\n# Body\n"


@pytest.mark.parametrize(
    "slug",
    [
        "my-concept",
        "a",
        "knowledge",
        "2026-08-13-knowledge-crud",
        "a/b",
        "pattern/rule-a",
        "a/b/c-d",
    ],
)
def test_validate_slug_accepts_kebab_segments(slug: str) -> None:
    assert validate_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "-leading",
        "trailing-",
        "double--dash",
        "UPPER",
        "snake_case",
        "space in",
        "..",
        "../etc/passwd",
        "a/../b",
        "/abs",
        "foo/",
        "foo//bar",
        "a\\b",
    ],
)
def test_validate_slug_rejects_invalid_shapes(slug: str) -> None:
    assert not validate_slug(slug)
    assert concept_path("/bundle", slug) is None


def test_relative_slug_strips_suffix_and_normalizes_separator() -> None:
    assert (
        relative_slug(Path("bundle"), Path("bundle/pattern/rule-a.md"))
        == "pattern/rule-a"
    )
    assert relative_slug(Path("bundle"), Path("outside/file.txt")) == "outside/file.txt"


def test_create_show_and_list_nested_concepts(tmp_path: Path) -> None:
    result = create(tmp_path, DOC, "pattern/rule-a")
    assert result.slug == "pattern/rule-a"
    assert result.version == version(DOC)
    shown = show(tmp_path, result.slug)
    assert shown.frontmatter["type"] == "decision"
    assert shown.body == "# Body\n"
    assert shown.version == result.version
    assert list_concepts(tmp_path) == [ListedConcept("pattern/rule-a", "decision")]


def test_create_rejects_missing_description_without_writing(tmp_path: Path) -> None:
    with pytest.raises(CreateError) as error:
        create(tmp_path, b"---\ntype: decision\n---\nbody\n", "missing-description")
    assert error.value.kind == "missing_description"
    assert not (tmp_path / "missing-description.md").exists()


def test_create_rejects_duplicate_and_invalid_slugs(tmp_path: Path) -> None:
    create(tmp_path, DOC, "same")
    with pytest.raises(CreateError) as duplicate:
        create(tmp_path, DOC, "same")
    assert duplicate.value.kind == "already_exists"
    with pytest.raises(CreateError) as invalid:
        create(tmp_path, DOC, "../escape")
    assert invalid.value.kind == "invalid_slug"
    assert not (tmp_path.parent / "escape.md").exists()


def test_show_missing_and_invalid_slug_errors(tmp_path: Path) -> None:
    with pytest.raises(ShowError) as missing:
        show(tmp_path, "nope")
    assert missing.value.kind == "not_found"
    with pytest.raises(ShowError) as invalid:
        show(tmp_path, "../outside")
    assert invalid.value.kind == "invalid_slug"


def test_list_reserved_missing_type_and_deprecated(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_text("# index\n")
    (tmp_path / "log.md").write_text("# log\n")
    (tmp_path / "untyped.md").write_text("---\ntitle: no type\n---\nbody\n")
    (tmp_path / "dead.md").write_text("---\ntype: old\nstatus: deprecated\n---\nbody\n")
    assert [entry.slug for entry in list_concepts(tmp_path)] == ["untyped"]
    assert list_concepts(tmp_path)[0].type_ is None
    assert {entry.slug for entry in list_concepts(tmp_path, True)} == {
        "dead",
        "untyped",
    }


def test_create_rejects_symlink_escape(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (bundle / "nested").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CreateError) as error:
        create(bundle, DOC, "nested/escape")
    assert error.value.kind == "invalid_slug"
    assert not (outside / "escape.md").exists()


def test_shared_invalid_slug_error_shape(tmp_path: Path) -> None:
    with pytest.raises(ConceptIoError) as error:
        from varde_learn.knowledge.crud import concept_path_or

        concept_path_or(tmp_path, "bad slug")
    assert error.value.kind == "invalid_slug"
