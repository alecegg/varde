from __future__ import annotations

import pytest
from varde_core.frontmatter import (
    FrontmatterError,
    frontmatter_bounds,
    parse,
    serialize,
)


def test_frontmatter_parse_and_round_trip() -> None:
    data = b"---\ntype: decision\ntitle: Test\n---\n# Body\n\nText.\n"
    frontmatter, body = parse(data)
    assert frontmatter == {"type": "decision", "title": "Test"}
    assert body == "# Body\n\nText.\n"
    assert parse(serialize(frontmatter, body)) == (frontmatter, body)


def test_frontmatter_exact_delimiter_and_empty_mapping() -> None:
    assert parse(b"---\n---\nbody") == ({}, "body")
    assert parse(b"---\n---\n") == ({}, "")
    data = b"---\ntext: |\n  ---not-close\n---\nbody"
    assert parse(data) == ({"text": "---not-close"}, "body")


@pytest.mark.parametrize(
    ("data", "bounds"),
    [
        (b"---\ntitle: x\n---\nbody", (4, 13)),
        (b"title: x\n---\nbody", None),
        (b"---\ntitle: x\nbody", None),
    ],
)
def test_frontmatter_bounds(data: bytes, bounds: tuple[int, int] | None) -> None:
    if bounds is None:
        with pytest.raises(ValueError):
            frontmatter_bounds(data)
    else:
        assert frontmatter_bounds(data) == bounds


@pytest.mark.parametrize(
    "data", [b"no markers", b"---\na: b", b"---\n- item\n---\nbody", b"\xff"]
)
def test_frontmatter_rejects_invalid_documents(data: bytes) -> None:
    with pytest.raises(FrontmatterError):
        parse(data)


def test_frontmatter_yaml_12_scalar_values() -> None:
    cases = [
        ("yes", "yes"),
        ("1.0", 1.0),
        ("'a: b'", "a: b"),
        ("null", None),
        ('"true"', "true"),
    ]
    for scalar, expected in cases:
        parsed, _ = parse(f"---\ntitle: {scalar}\n---\nbody\n".encode())
        assert parsed["title"] == expected


def test_frontmatter_errors_use_compact_rust_compatible_text() -> None:
    try:
        parse("---\nnot: [valid\n---\n")
    except FrontmatterError as exc:
        assert str(exc) == (
            "invalid YAML frontmatter: did not find expected ',' or ']' at line 2 "
            "column 1, "
            "while parsing a flow sequence at line 1 column 6"
        )
    else:
        raise AssertionError("invalid YAML must fail")

    try:
        parse("---\n[]\n---\n")
    except FrontmatterError as exc:
        assert str(exc) == (
            "frontmatter must be a YAML mapping, got expected a YAML mapping, "
            "e.g. `type: decision`"
        )
    else:
        raise AssertionError("non-mapping YAML must fail")
