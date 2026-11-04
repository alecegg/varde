from typing import Any

import pytest
from varde_learn.memory import ops, store
from varde_learn.memory.entry import Entry
from varde_learn.memory.ops import EntryRef, OpsError

REF = EntryRef("global", "", "e1")
NOW = "2026-11-02T00:00:00Z"


def make(entry_id: str = "e1", **overrides: Any) -> Entry:
    base: dict[str, Any] = {
        "id": entry_id,
        "scope": "global",
        "scope_key": "",
        "text": "short summary\nbody",
        "source": "t",
        "created": "2026-11-01T00:00:00Z",
    }
    base.update(overrides)
    return Entry(**base)


def seed(tmp_path, entry: Entry | None = None) -> str:
    store.write_entry(tmp_path, entry or make())
    return ops.read_stored(tmp_path, REF).version


def test_entry_ops_update_sets_updated_keeps_created(tmp_path) -> None:
    current = seed(tmp_path)
    result = ops.update_entry(tmp_path, REF, current, {"text": "new\nbody"}, NOW)
    assert result.entry is not None
    assert (result.entry.updated, result.entry.created) == (NOW, make().created)
    assert result.entry.text == "new\nbody"
    assert result.version == ops.read_stored(tmp_path, REF).version != current


def test_entry_ops_occ_conflict_writes_nothing(tmp_path) -> None:
    current = seed(tmp_path)
    ops.update_entry(tmp_path, REF, current, {"topic": "a"}, NOW)
    before = store.entry_path(tmp_path, "global", "", "e1").read_bytes()
    with pytest.raises(OpsError) as error:
        ops.update_entry(tmp_path, REF, current, {"topic": "b"}, NOW)
    assert error.value.kind == "conflict"
    assert store.entry_path(tmp_path, "global", "", "e1").read_bytes() == before


def test_entry_ops_set_field_known_extra_and_coercion(tmp_path) -> None:
    current = seed(tmp_path)
    one = ops.set_field(tmp_path, REF, current, ("tags", "a, b"), NOW)
    two = ops.set_field(tmp_path, REF, one.version, ("owner", "me"), NOW)
    three = ops.set_field(tmp_path, REF, two.version, ("surface", "false"), NOW)
    assert three.entry is not None
    assert three.entry.tags == ("a", "b")
    assert three.entry.extra == {"owner": "me"}
    assert three.entry.surface is False
    with pytest.raises(OpsError) as error:
        ops.set_field(tmp_path, REF, three.version, ("surface", "maybe"), NOW)
    assert error.value.kind == "invalid"


def test_entry_ops_immutable_fields_refused(tmp_path) -> None:
    current = seed(tmp_path)
    for name in ("created", "id", "scope", "updated"):
        with pytest.raises(OpsError) as error:
            ops.set_field(tmp_path, REF, current, (name, "x"), NOW)
        assert error.value.kind == "immutable"


def test_entry_ops_lint_errors_block_write(tmp_path) -> None:
    current = seed(tmp_path)
    before = store.entry_path(tmp_path, "global", "", "e1").read_bytes()
    bad = [
        {"text": "  "},
        {"text": "password = hunter22222"},
        {"valid_until": "soon"},
        {"description": "x" * 90},
        {"title": "api_key = abcdefgh12345"},
    ]
    for changes in bad:
        with pytest.raises(OpsError) as error:
            ops.update_entry(tmp_path, REF, current, changes, NOW)
        assert error.value.kind == "lint"
        assert error.value.issues
    assert store.entry_path(tmp_path, "global", "", "e1").read_bytes() == before


def test_entry_ops_legacy_long_summary_grandfathered(tmp_path) -> None:
    legacy = make(text="x" * 90 + "\nbody")
    current = seed(tmp_path, legacy)
    result = ops.update_entry(tmp_path, REF, current, {"topic": "t"}, NOW)
    assert [i.code for i in result.issues] == ["summary-surface"]


def test_entry_ops_retire_keeps_file(tmp_path) -> None:
    current = seed(tmp_path)
    result = ops.retire_entry(tmp_path, REF, current, NOW)
    assert result.entry is not None
    assert result.entry.status == "retired"
    assert result.path.exists()


def test_entry_ops_delete_reports_inbound_links(tmp_path) -> None:
    store.write_entry(tmp_path, make("e2", text="see\n[e1](e1.md)"))
    current = seed(tmp_path)
    result = ops.delete_entry(tmp_path, REF, current)
    assert result.entry is None
    assert result.linked_by == ("global/e2.md",)
    assert not result.path.exists()
    with pytest.raises(OpsError) as error:
        ops.delete_entry(tmp_path, REF, current)
    assert error.value.kind == "not_found"


def test_entry_ops_delete_conflict_keeps_file(tmp_path) -> None:
    seed(tmp_path)
    with pytest.raises(OpsError) as error:
        ops.delete_entry(tmp_path, REF, "0" * 16)
    assert error.value.kind == "conflict"
    assert store.entry_path(tmp_path, "global", "", "e1").exists()


def test_entry_ops_resolve_ref(tmp_path) -> None:
    seed(tmp_path)
    key = "repo-0123456789abcdef"
    store.write_entry(tmp_path, make("e1", scope="project", scope_key=key))
    with pytest.raises(OpsError) as error:
        ops.resolve_ref(tmp_path, "e1")
    assert error.value.kind == "ambiguous"
    with pytest.raises(OpsError):
        ops.resolve_ref(tmp_path, "nope")
    store.write_entry(tmp_path, make("e9"))
    assert ops.resolve_ref(tmp_path, "e9") == EntryRef("global", "", "e9")


def test_entry_ops_field_filter_matches_registry_semantics() -> None:
    entries = [
        make("a", tags=("x", "y"), type="decision", extra={"owner": "me"}),
        make("b", surface=False),
    ]
    assert [e.id for e in ops.filter_entries(entries, [("tags", "y")])] == ["a"]
    assert [e.id for e in ops.filter_entries(entries, [("surface", "false")])] == ["b"]
    assert [e.id for e in ops.filter_entries(entries, [("owner", "me")])] == ["a"]
    assert ops.filter_entries(entries, [("type", "nope")]) == []
