from typing import Any

import pytest
from varde_learn.memory.entry import (
    Entry,
    EntryError,
    find_secret,
    is_project_key,
    is_slug,
    validate,
)

KEY = "My Repo_X-0123456789abcdef"


def make(**overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": "e1",
        "scope": "global",
        "scope_key": "",
        "text": "note",
        "source": "test",
        "created": "2026-11-01T00:00:00Z",
    }
    base.update(overrides)
    return Entry(**base)


def test_valid_entries_per_scope() -> None:
    validate(make())
    validate(make(scope="skill", scope_key="varde-build", project=KEY))
    validate(make(scope="project", scope_key=KEY))
    validate(make(scope="agent", scope_key="builder", model="m", harness_version="1"))


@pytest.mark.parametrize("missing", ["model", "harness_version"])
def test_agent_entry_requires_model_and_harness(missing) -> None:
    fields = {"model": "m", "harness_version": "1"}
    fields[missing] = ""
    with pytest.raises(EntryError):
        validate(make(scope="agent", scope_key="builder", **fields))


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": "team"},
        {"scope": "skill", "scope_key": ""},
        {"scope": "project", "scope_key": ""},
        {"text": "  \n"},
        {"status": "gone"},
        {"id": "../x"},
        {"id": "a/b"},
        {"scope": "skill", "scope_key": "../x"},
        {"scope": "skill", "scope_key": "a/b"},
        {"scope": "agent", "scope_key": "..", "model": "m", "harness_version": "1"},
        {"scope_key": "x"},
        {"project": KEY},
        {"scope": "project", "scope_key": KEY, "project": KEY},
        {"scope": "skill", "scope_key": "s", "project": "../x-0123456789abcdef"},
    ],
)
def test_rejections(overrides) -> None:
    with pytest.raises(EntryError):
        validate(make(**overrides))


def test_slug_and_project_key_rules() -> None:
    assert is_slug("a.b_c-1")
    assert not is_slug("")
    assert not is_slug("A")
    assert not is_slug(".")
    assert is_project_key(KEY)
    assert is_project_key("Personal-Notes-0123456789abcdef")
    assert not is_project_key("../x-0123456789abcdef")
    assert not is_project_key("a/b-0123456789abcdef")
    assert not is_project_key("a\x00b-0123456789abcdef")
    assert not is_project_key("a\nb-0123456789abcdef")
    assert not is_project_key("x-0123456789abcdeg")
    assert not is_project_key("..-0123456789abcdef")


SECRETS = [
    "-----BEGIN RSA PRIVATE KEY-----",
    "AKIA" + "A" * 16,
    "ghp_" + "a" * 20,
    "github_pat_abc",
    "sk-" + "a" * 20,
    "xoxb-123",
    "Authorization: Bearer abc",
    "password = hunter2hunter2",
    "api_key: abcdefgh1",
    "token=abcdefgh",
    "secret: abcdefgh",
    "passwd=abcdefgh",
]


@pytest.mark.parametrize("text", SECRETS)
def test_secret_patterns(text) -> None:
    assert find_secret(f"prefix {text} suffix") is not None
    with pytest.raises(EntryError):
        validate(make(text=text))


def test_plain_text_is_not_secret() -> None:
    assert find_secret("prefer small commits; the token budget is 5") is None


def test_unified_model_defaults_read_as_lesson_surfaced() -> None:
    entry = make()
    assert entry.type == "lesson"
    assert entry.surface is True
    assert entry.aliases == ()
    assert entry.extra == {}


def test_unified_model_concept_reader_maps_fields() -> None:
    from varde_learn.knowledge.concept import Concept
    from varde_learn.memory.entry import entry_from_concept

    data = (
        b"---\ntype: decision\nstatus: current\ndate: 2026-10-16\n"
        b"aliases: [cutover]\ntags: [a]\nowner: me\n---\n# Cutover\n\nbody\n"
    )
    entry, warnings = entry_from_concept(
        Concept.from_bytes(data, "explorations/cutover"),
        scope_key=KEY,
        source="knowledge:b:explorations/cutover",
    )
    assert warnings == []
    assert entry.id == "explorations-cutover"
    assert (entry.scope, entry.type, entry.status, entry.surface) == (
        "project",
        "decision",
        "active",
        False,
    )
    assert entry.created == "2026-10-16"
    assert entry.aliases == ("cutover",)
    assert entry.description == "Cutover"
    assert entry.extra == {"owner": "me"}
    validate(entry)


def test_unified_model_concept_without_front_matter() -> None:
    from varde_learn.knowledge.concept import Concept
    from varde_learn.memory.entry import entry_from_concept

    entry, warnings = entry_from_concept(
        Concept("backlog", {}, "# Backlog\n\ntext\n"),
        scope_key=KEY,
        source="s",
        mtime_date="2026-11-01",
    )
    assert (entry.type, entry.status, entry.created) == (
        "reference",
        "active",
        "2026-11-01",
    )
    assert entry.description == "Backlog"
    assert warnings == []


def test_unified_model_concept_warns_on_unknown_status_and_type() -> None:
    from varde_learn.knowledge.concept import Concept
    from varde_learn.memory.entry import entry_from_concept

    entry, warnings = entry_from_concept(
        Concept.from_bytes(b"---\ntype: weird\nstatus: odd\n---\nx\n", "c"),
        scope_key=KEY,
        source="s",
    )
    assert entry.status == "active"
    assert len(warnings) == 2
