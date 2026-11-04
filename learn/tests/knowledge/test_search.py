from __future__ import annotations

import json
import shutil
from pathlib import Path

from varde_learn.knowledge.crud.search import (
    query_terms,
    search_text,
    search_text_matching,
)
from varde_learn.module import register


def _write(bundle: Path, name: str, content: str) -> None:
    path = bundle / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_query_terms_normalize_dedupe_and_drop_short_tokens() -> None:
    assert query_terms("Rust rust a RUST-lang") == ["rust", "lang"]
    assert query_terms("a I x") == []


def test_ranking_scores_and_previews(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "titled.md",
        (
            "---\ntype: decision\ntitle: Postgres tuning\n---\n# Notes\n"
            "Unrelated content.\n"
        ),
    )
    _write(
        tmp_path,
        "body-only.md",
        (
            "---\ntype: decision\ntitle: Something else\n---\n# Notes\n"
            "Postgres appears only here.\n"
        ),
    )
    _write(
        tmp_path,
        "chunk.md",
        (
            "---\ntype: decision\ntitle: Doc\n---\nIntro text, unrelated.\n\n"
            "## Configuration\nSet the widget flag to enable turbo mode.\n\n"
            "## Other\nNot relevant here.\n"
        ),
    )

    assert [hit.as_dict() for hit in search_text([tmp_path], "postgres", 20)] == [
        {
            "slug": "titled",
            "type": "decision",
            "score": 5,
            "preview": "# Notes Unrelated content.",
        },
        {
            "slug": "body-only",
            "type": "decision",
            "score": 1,
            "preview": "#Notes — Postgres appears only here.",
        },
    ]
    assert [hit.as_dict() for hit in search_text([tmp_path], "turbo", 20)] == [
        {
            "slug": "chunk",
            "type": "decision",
            "score": 1,
            "preview": "#Configuration — Set the widget flag to enable turbo mode.",
        }
    ]


def test_frontmatter_weights_slug_ties_filters_and_bundle_precedence(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _write(
        first,
        "use-rust.md",
        (
            "---\ntype: decision\ntitle: Rust\naliases: [rusty]\ntags: [rust]\n"
            "status: stable\n---\n# Rust\nBody\n"
        ),
    )
    _write(
        first,
        "b.md",
        "---\ntype: decision\ntitle: Rust\n---\n# Rust\nRust rust rust.\n",
    )
    _write(
        first,
        "a.md",
        "---\ntype: decision\ntitle: Rust\n---\n# Rust\nRust rust rust.\n",
    )
    _write(
        second,
        "use-rust.md",
        (
            "---\ntype: decision\ntitle: Rust\naliases: [rusty]\ntags: [rust]\n"
            "status: stable\n---\n# Rust\nSecond bundle.\n"
        ),
    )

    hits = search_text([first], "rust", 20)
    assert [(hit.slug, hit.score) for hit in hits] == [
        ("use-rust", 22),
        ("a", 10),
        ("b", 10),
    ]
    assert (
        search_text_matching([first], "rust", [("status", "stable")], 20)[0].slug
        == "use-rust"
    )
    assert search_text_matching([first], "rust", [("status", "draft")], 20) == []
    assert (
        search_text([first, second], "rust", 20)[0].preview == "#Rust — Second bundle."
    )


def test_walk_rules_missing_type_and_fallback_preview(tmp_path: Path) -> None:
    _write(tmp_path, "index.md", "# Rust index")
    _write(tmp_path, "README.md", "# Rust readme")
    _write(tmp_path, ".hidden.md", "---\ntitle: Rust\n---\nHidden\n")
    _write(tmp_path, "target/ignored.md", "---\ntitle: Rust\n---\nIgnored\n")
    _write(
        tmp_path,
        "intro.md",
        (
            "---\ntitle: Widget alpha\n---\n"
            "Just an intro paragraph with no headings at all.\n"
        ),
    )
    _write(
        tmp_path,
        "nested/missing-type.md",
        "---\ntitle: Rust\n---\nRust in a nested file.\n",
    )

    hits = search_text([tmp_path], "rust", 20)
    assert [hit.as_dict() for hit in hits] == [
        {
            "slug": "nested/missing-type",
            "type": None,
            "score": 6,
            "preview": "Rust in a nested file.",
        }
    ]
    assert (
        search_text([tmp_path], "widget", 20)[0].preview
        == "Just an intro paragraph with no headings at all."
    )
    assert search_text([tmp_path], " ", 20) == []


FIXTURE = Path(__file__).parent / "fixtures" / "real-bundle"
QUERIES = (
    "cutover",
    "port",
    "report",
    "python port backlog",
    "zebra",
    "sub",
    "mnemonic",
)


def _cli_results(bundle: Path, query: str, capsys) -> list[dict]:
    argv = ["knowledge", "search", "--bundle", str(bundle), "--text", query, "--json"]
    assert register().run(argv) == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_cli_text_search_matches_old_scorer_on_real_bundle(
    tmp_path: Path, capsys
) -> None:
    # the old walk aborts on the front-matter-less backlog file, so leave it out
    bundle = tmp_path / "bundle"
    shutil.copytree(FIXTURE, bundle)
    (bundle / "backlog-python-port.md").unlink()
    for query in QUERIES:
        old = [r.as_dict() for r in search_text([bundle], query, 20)]
        assert _cli_results(bundle, query, capsys) == old


def test_cli_text_search_keeps_uppercase_slug_and_secret_prose(
    tmp_path: Path, capsys
) -> None:
    _write(tmp_path, "Cutover.md", "---\ntype: note\n---\nCutover plan report.\n")
    _write(
        tmp_path,
        "sub/secret-note.md",
        "---\nowner: zebra\n---\nPassword: abcdefgh12345\n",
    )
    for query in ("cutover", "port", "zebra", "sub", "abcdefgh12345"):
        old = [r.as_dict() for r in search_text([tmp_path], query, 20)]
        assert old
        assert _cli_results(tmp_path, query, capsys) == old
