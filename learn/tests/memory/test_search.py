from datetime import date
from pathlib import Path
from typing import Any

import pytest
from varde_learn.memory import search as lib
from varde_learn.memory import searchindex, store
from varde_learn.memory.entry import Entry
from varde_learn.memory.search import SearchOptions

KEY = "repo-0123456789abcdef"
TODAY = date(2026, 11, 1)


def make(entry_id: str, text: str, **overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": "global",
        "scope_key": "",
        "text": text,
        "source": "t",
        "created": "c",
    }
    base.update(overrides)
    return Entry(**base)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "mem"
    for entry in (
        make("t", "plain\nunrelated", title="Postgres tuning"),
        make("b", "plain\npostgres appears only in the body"),
        make("old", "postgres stale", valid_until="2026-01-01"),
        make("topical", "postgres topical", topic="db", tags=("sql",)),
        make("p", "postgres project", scope="project", scope_key=KEY),
    ):
        store.write_entry(root, entry)
    return searchindex.memory_source(root)


def ids(hits) -> list[str]:
    return [hit.slug for hit in hits]


def options(**kwargs: Any) -> SearchOptions:
    return SearchOptions(today=TODAY, **kwargs)


def test_search_title_outranks_body_and_expired_hidden(source) -> None:
    hits = lib.search(source, "postgres", options())
    assert ids(hits)[0] == "t"
    assert "old" not in ids(hits)
    assert set(ids(hits)) == {"t", "b", "topical", "p"}
    assert all(isinstance(h.score, int) and h.score >= 1 for h in hits)


def test_search_include_expired(source) -> None:
    hits = lib.search(source, "postgres", options(include_expired=True))
    assert "old" in ids(hits)


def test_search_topic_scope_and_field_filters(source) -> None:
    assert ids(lib.search(source, "postgres", options(topic="db"))) == ["topical"]
    assert ids(lib.search(source, "postgres", options(scopes=("project",)))) == ["p"]
    assert ids(lib.search(source, "postgres", options(filters=(("tags", "sql"),)))) == [
        "topical"
    ]


def test_search_limit_and_empty_terms(source) -> None:
    assert len(lib.search(source, "postgres", options(limit=2))) == 2
    assert lib.search(source, "a I", options()) == []
    assert lib.search(source, "zzznomatch", options()) == []


def test_search_preview_uses_matching_chunk(source) -> None:
    hit = next(h for h in lib.search(source, "postgres", options()) if h.slug == "b")
    assert hit.preview == "plain postgres appears only in the body"


def test_search_ties_are_ordered_by_slug(tmp_path) -> None:
    root = tmp_path / "mem"
    for name in ("b", "a"):
        store.write_entry(root, make(name, "same words here"))
    hits = lib.search(searchindex.memory_source(root), "words", options())
    assert ids(hits) == ["a", "b"]


def test_search_fallback_without_fts_prints_one_notice(
    source, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(searchindex, "fts5_available", lambda: False)
    monkeypatch.setattr(lib, "_notice_printed", False)
    first = lib.search(source, "postgres", options())
    lib.search(source, "postgres", options())
    assert ids(first)[0] == "t"
    assert capsys.readouterr().err.count("notice:") == 1


def test_search_uses_persistent_index_file(source, tmp_path) -> None:
    index = tmp_path / "idx" / "i.sqlite"
    first = lib.search(source, "postgres", options(), index)
    assert index.exists()
    assert ids(lib.search(source, "postgres", options(), index)) == ids(first)


def test_search_library_has_no_embedding_or_network_imports() -> None:
    text = Path(lib.__file__).read_text(encoding="utf-8").lower()
    for word in ("embedding", "sqlite_vec", "openai", "anthropic"):
        assert word not in text


@pytest.fixture
def fielded(tmp_path):
    root = tmp_path / "mem"
    for entry in (
        make("zebra-notes", "plain words", extra={"owner": {"team": ["zebra"]}}),
        make("report-card", "plain words"),
        make("other", "plain words", source="knowledge:b:sub/secret-note"),
    ):
        store.write_entry(root, entry)
    return searchindex.memory_source(root)


def test_search_finds_slug_and_extra_values(fielded) -> None:
    assert ids(lib.search(fielded, "zebra", options())) == ["zebra-notes"]
    assert ids(lib.search(fielded, "sub", options())) == ["other"]
    assert ids(lib.search(fielded, "report", options())) == ["report-card"]


def test_search_substring_matches_inside_words(fielded) -> None:
    assert lib.search(fielded, "port", options()) == []
    assert ids(lib.search_substring(fielded, "port", options())) == ["report-card"]
    assert ids(lib.search_substring(fielded, "zebra", options())) == ["zebra-notes"]
    assert ids(lib.search_substring(fielded, "sub", options())) == ["other"]


def test_search_substring_honors_filters_and_expiry(source) -> None:
    hits = lib.search_substring(source, "postgres", options(scopes=("project",)))
    assert ids(hits) == ["p"]
    assert "old" not in ids(lib.search_substring(source, "postgres", options()))
