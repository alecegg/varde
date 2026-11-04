from __future__ import annotations

from pathlib import Path

import pytest
from varde_learn.loop.importer import (
    normalize_repo_root,
    parse_markdown,
    read_import_files,
    slugify,
    split_frontmatter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "import" / "yaml-edge"


def test_legacy_scalars_match_serde_yaml_value_types() -> None:
    entry = parse_markdown(
        (FIXTURES / "legacy-scalars.md").read_text(),
        FIXTURES / "legacy-scalars.md",
        "/repo",
    )
    occurrence = entry.occurrences[0]

    assert entry.created_at == "2025-10-15"
    assert occurrence.at == "2025-10-15"
    assert occurrence.cwd == "/repo"
    assert occurrence.head_sha == "yes"
    assert occurrence.cost == "17"
    assert entry.target == "null"


@pytest.mark.parametrize("scalar", ["yes", "no", "on", "off"])
def test_yaml_11_boolean_spellings_remain_strings(scalar: str) -> None:
    path = FIXTURES / f"boolean-{scalar}.md"
    entry = parse_markdown(path.read_text(), path, "/repo")
    assert entry.occurrences[0].head_sha == scalar


def test_null_and_quoted_scalars() -> None:
    content = (
        '---\ntype: friction\nhead_sha: null\ncost: "17"\n'
        'target: "null"\n---\nevidence\n'
    )
    entry = parse_markdown(content, Path("item.md"), "/repo")
    assert entry.occurrences[0].head_sha is None
    assert entry.occurrences[0].cost == "17"
    assert entry.target == "null"


def test_structured_export_tags_round_trip() -> None:
    content = (
        '---\nformat: "varde-friction-item"\nversion: 1\nid: 1\n'
        'slug: "tagged"\ntitle: "Tagged item"\nsource: "test"\n'
        'repo_root: null\nstatus: "open"\ntarget: null\n'
        'tags: ["speed", "token"]\ncreated_at: "2025-01-01"\n'
        "occurrences: []\nstatus_changes: []\n---\n"
    )
    entry = parse_markdown(content, Path("tagged.md"), "/repo")
    assert entry.tags == ["speed", "token"]


@pytest.mark.parametrize(
    ("scalar", "expected"),
    [
        ("1:30", "1:30"),
        ("017", "017"),
        ("1_000", "1_000"),
        ("0o17", "15"),
        (".inf", ".inf"),
        (".nan", ".nan"),
        ("1e3", "1000.0"),
    ],
)
def test_legacy_import_scalars_match_serde_yaml(scalar: str, expected: str) -> None:
    entry = parse_markdown(
        f"---\ntype: friction\nhead_sha: {scalar}\n---\nevidence\n",
        Path("item.md"),
        "/repo",
    )
    assert entry.occurrences[0].head_sha == expected


def test_yaml_duplicate_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate entry with key"):
        parse_markdown(
            "---\ntype: friction\ntitle: one\ntitle: two\n---\nevidence\n",
            Path("item.md"),
            "/repo",
        )


def test_yaml_complex_keys_do_not_break_import() -> None:
    entry = parse_markdown(
        "---\ntype: friction\n? [unused]\n: value\n---\nevidence\n",
        Path("item.md"),
        "/repo",
    )
    assert entry.title == "Item"


def test_legacy_import_rejects_boolean_provenance_scalar() -> None:
    with pytest.raises(ValueError, match="head_sha.*scalar string or number"):
        parse_markdown(
            "---\ntype: friction\nhead_sha: true\n---\nevidence\n",
            Path("item.md"),
            "/repo",
        )


def test_legacy_import_without_date_uses_a_timestamp() -> None:
    entry = parse_markdown(
        "---\ntype: friction\n---\nevidence\n", Path("item.md"), "/repo"
    )
    assert entry.created_at is None
    assert entry.occurrences[0].at.endswith("Z")


def test_structured_date_scalars_are_strings() -> None:
    entry = parse_markdown(
        (FIXTURES / "structured-date.md").read_text(),
        FIXTURES / "structured-date.md",
        "/repo",
    )
    assert (entry.id, entry.slug, entry.title, entry.created_at) == (
        9,
        "2025-10-15",
        "2025-10-15",
        "2025-10-15",
    )


def test_required_string_rejects_unquoted_integer() -> None:
    with pytest.raises(ValueError, match="missing or invalid `title` string"):
        parse_markdown(
            (FIXTURES / "structured-invalid-required.md").read_text(),
            FIXTURES / "structured-invalid-required.md",
            "/repo",
        )


def test_structured_occurrences_and_status_changes() -> None:
    content = """---
format: varde-friction-item
version: 1
id: 4
slug: stable-item
title: Stable item
source: import
status: RESOLVED
created_at: now
occurrences:
  - id: 7
    item_id: 4
    at: then
    cwd: /repo
    repo_root: null
    head_sha: abc
    evidence: observed
    cost: "12"
status_changes:
  - id: 8
    item_id: 4
    at: later
    from_status: open
    to_status: resolved
    reason: fixed
---
"""

    entry = parse_markdown(content, Path("item.md"), "/repo")

    assert entry.status.value == "resolved"
    assert entry.occurrences[0].cost == "12"
    assert entry.occurrences[0].repo_root is None
    assert entry.status_changes[0].to_status == "resolved"


def test_legacy_blank_cwd_is_rejected() -> None:
    content = "---\ntype: friction\ncwd: ''\n---\nevidence\n"
    with pytest.raises(ValueError, match="`cwd` must not be blank"):
        parse_markdown(content, Path("item.md"), "/repo")


def test_read_import_files_sorts_markdown_and_skips_non_regular_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.md").write_text("not frontmatter")
    (tmp_path / "a.md").write_text("---\ntype: friction\n---\nEvidence\n")
    (tmp_path / "ignored.txt").write_text("ignored")
    (tmp_path / "link.MD").symlink_to(tmp_path / "a.md")
    (tmp_path / "directory.md").mkdir()

    files = read_import_files(tmp_path, tmp_path)

    assert [item.file for item in files] == ["a.md", "b.md", "directory.md", "link.MD"]
    assert files[0].entry is not None
    assert files[1].reason == "missing YAML frontmatter opening delimiter"
    assert files[2].reason == "not a regular Markdown file"
    assert files[3].reason == "symbolic links are not imported"
    assert [item.entry for item in files[1:]] == [None, None, None]


def test_split_frontmatter_handles_crlf_and_empty_body() -> None:
    assert split_frontmatter("---\r\ntype: friction\r\n---\r\n\r\n") == (
        "type: friction\r\n",
        "",
    )


def test_slugify_and_repo_root_normalization(tmp_path: Path) -> None:
    assert slugify("RÉSULTAT 42") == "r-sultat-42"
    assert slugify("123") == "friction-123"
    normalized = Path(normalize_repo_root(tmp_path))
    assert normalized.is_absolute() and normalized.samefile(tmp_path)
