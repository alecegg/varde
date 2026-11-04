from pathlib import Path

from varde_learn.memory import migration_record, sources, store
from varde_learn.memory.entry import Entry

KEY = "repo-0123456789abcdef"

FILES = {
    "alpha.md": (
        "---\ntype: decision\ndescription: Alpha call\ntags: [a]\n"
        "date: 2026-01-02\n---\n# Alpha\nbody\n"
    ),
    "beta.md": "---\nstatus: current\ndescription: Beta\n---\nbeta body\n",
    "notes/gamma.md": "---\ntype: pattern\nowner: me\n---\n# Gamma\ntext\n",
    "notes/deep/delta.md": "---\ndescription: Delta\n---\ndelta\n",
    "plain.md": "# Plain heading\nno front matter here\n",
    "index.md": "---\ntype: index\n---\nreserved\n",
}


def make_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    for name, text in FILES.items():
        path = bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return bundle


def test_bundle_loader_flat_and_nested_slugs(tmp_path) -> None:
    entries, issues = sources.load_bundle(make_bundle(tmp_path), scope_key=KEY)
    by_id = {e.id: e for e in entries}
    assert sorted(by_id) == [
        "alpha",
        "beta",
        "notes-deep-delta",
        "notes-gamma",
        "plain",
    ]
    assert not [i for i in issues if i.severity == "error"]
    assert by_id["alpha"].type == "decision"
    assert by_id["alpha"].created == "2026-01-02"
    assert by_id["notes-gamma"].extra == {"owner": "me"}
    assert by_id["notes-gamma"].source == "knowledge:bundle:notes/gamma"
    assert all(not e.surface and e.scope == "project" for e in entries)


def test_bundle_loader_file_without_front_matter(tmp_path) -> None:
    entries, _ = sources.load_bundle(make_bundle(tmp_path), scope_key=KEY)
    plain = next(e for e in entries if e.id == "plain")
    assert plain.type == "reference"
    assert plain.status == "active"
    assert plain.description == "Plain heading"


def test_bundle_loader_reports_but_keeps_invalid_concepts(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    (bundle / "Bad Name.md").write_text("---\ndescription: x\n---\nbody\n")
    (bundle / "notes-gamma.md").write_text("---\ndescription: x\n---\nbody\n")
    (bundle / "Secret.md").write_text("Password: abcdefgh12345\n")
    entries, issues = sources.load_bundle(bundle, scope_key=KEY)
    assert not [i for i in issues if i.severity == "error"]
    assert len([i for i in issues if i.code == "concept-entry"]) >= 3
    assert len(entries) == 5 + 3
    assert "Bad Name" in {e.id for e in entries}


def test_memory_loader_round_trip(tmp_path) -> None:
    entry = Entry(
        id="e1", scope="global", scope_key="", text="body", source="t", created="c"
    )
    store.write_entry(tmp_path, entry)
    entries, issues = sources.load_memory(tmp_path)
    assert entries == [entry]
    assert issues == []


def test_migration_record_round_trip(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    root = tmp_path / "mem"
    assert migration_record.read_record(root, bundle) is None
    path = migration_record.write_record(root, bundle, {"p1": "v1"})
    assert path.parent == root / ".migrations"
    assert path.name.startswith("knowledge-")
    record = migration_record.read_record(root, bundle)
    assert record is not None
    assert record["created"] == {"p1": "v1"}
    assert migration_record.remove_record(root, bundle)
    assert not migration_record.remove_record(root, bundle)
    assert migration_record.read_record(root, bundle) is None


def test_migrate_single_reader(tmp_path) -> None:
    bundle = make_bundle(tmp_path)
    root = tmp_path / "mem"
    store.write_entry(
        root,
        Entry(
            id="alpha",
            scope="project",
            scope_key=KEY,
            text="migrated",
            source="knowledge:bundle:alpha",
            created="c",
        ),
    )
    before, _ = sources.loader_for(root, bundle, scope_key=KEY)()
    assert len(before) == 5
    assert {e.text for e in before if e.id == "alpha"} != {"migrated"}
    migration_record.write_record(root, bundle, {})
    after, _ = sources.loader_for(root, bundle, scope_key=KEY)()
    assert [e.id for e in after] == ["alpha"]
    assert after[0].text == "migrated"
    migration_record.remove_record(root, bundle)
    again, _ = sources.loader_for(root, bundle, scope_key=KEY)()
    assert len(again) == 5
