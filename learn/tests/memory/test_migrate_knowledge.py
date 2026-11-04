from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from varde_learn.loop import cli_memory
from varde_learn.memory import migrate_knowledge as mk
from varde_learn.memory import migration_record, sources, store

KEY = "repo-0123456789abcdef"
REAL = Path(__file__).parent / "fixtures" / "knowledge-real"


def digest(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


@pytest.fixture
def bundle(tmp_path) -> Path:
    target = tmp_path / "knowledge-real"
    shutil.copytree(REAL, target)
    return target


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "mem"


def test_migrate_knowledge_dry_run_reports_and_writes_nothing(bundle, root) -> None:
    plan = mk.plan_migration(bundle, root, KEY)
    assert plan.files == 8
    assert len(plan.planned) == 8
    assert plan.type_counts() == {"decision": 1, "reference": 7}
    assert plan.collisions == [] and plan.rejects == []
    assert files_under(root) == []


def test_migrate_knowledge_apply_rerun_and_undo(bundle, root) -> None:
    before = digest(bundle)
    first = mk.apply_migration(root, mk.plan_migration(bundle, root, KEY))
    assert len(first.created) == 8 and first.record is not None
    entries, _ = store.load_report(root)
    assert len(entries) == 8
    assert all(not e.surface and e.scope == "project" for e in entries)
    assert all(e.source.startswith("knowledge:knowledge-real:") for e in entries)
    second = mk.apply_migration(root, mk.plan_migration(bundle, root, KEY))
    assert second.created == [] and len(second.unchanged) == 8
    undone = mk.undo_migration(root, bundle)
    assert sorted(undone.removed) == sorted(first.created)
    assert undone.skipped == [] and undone.record_removed
    assert store.load_report(root)[0] == []
    assert migration_record.read_record(root, bundle) is None
    assert digest(bundle) == before


def test_migrate_knowledge_undo_skips_edited_file(bundle, root) -> None:
    first = mk.apply_migration(root, mk.plan_migration(bundle, root, KEY))
    edited = first.created[0]
    edited.write_text(edited.read_text() + "\nhuman edit\n", encoding="utf-8")
    undone = mk.undo_migration(root, bundle)
    assert undone.skipped == [edited] and edited.exists()
    assert len(undone.removed) == 7


def write(bundle: Path, name: str, text: str) -> None:
    path = bundle / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_migrate_knowledge_secret_rejects_that_file_only(tmp_path, root) -> None:
    bundle = tmp_path / "b"
    write(bundle, "good.md", "---\ntype: reference\n---\n\n# Good\n\nfine\n")
    write(
        bundle,
        "bad.md",
        "---\ntype: reference\n---\n\n# Bad\n\npassword: abcdefgh12345\n",
    )
    plan = mk.plan_migration(bundle, root, KEY)
    assert [r.slug for r in plan.rejects] == ["bad"] and plan.rejects[
        0
    ].kind == "secret"
    result = mk.apply_migration(root, plan)
    assert [p.name for p in result.created] == ["good.md"]
    assert [p.name for p in files_under(root / "project") if p.suffix == ".md"] == [
        "good.md"
    ]


def test_migrate_knowledge_secret_in_front_matter_extra(tmp_path, root) -> None:
    bundle = tmp_path / "b"
    write(
        bundle,
        "x.md",
        "---\ntype: reference\nowner: token = abcdefgh12345\n---\n\n# X\n\nok\n",
    )
    plan = mk.plan_migration(bundle, root, KEY)
    assert plan.planned == [] and plan.rejects[0].kind == "secret"


def test_migrate_knowledge_collision_is_reported_not_written(tmp_path, root) -> None:
    bundle = tmp_path / "b"
    write(bundle, "a/b.md", "# One\n\nfirst\n")
    write(bundle, "a-b.md", "# Two\n\nsecond\n")
    write(bundle, "solo.md", "# Solo\n\nthird\n")
    plan = mk.plan_migration(bundle, root, KEY)
    assert sorted(r.slug for r in plan.collisions) == ["a-b", "a/b"]
    assert [p.slug for p in plan.planned] == ["solo"]


def test_migrate_knowledge_rewrites_links_and_reports_broken(tmp_path, root) -> None:
    bundle = tmp_path / "b"
    write(
        bundle, "topic/one.md", "# One\n\nsee [two](../two.md) and [gone](missing.md)\n"
    )
    write(bundle, "two.md", "# Two\n\nback to [one](topic/one.md#x)\n")
    plan = mk.plan_migration(bundle, root, KEY)
    changes = {(c.slug, c.link): c.target for c in plan.links}
    assert changes[("topic/one", "../two.md")] == "two.md"
    assert changes[("topic/one", "missing.md")] == ""
    assert changes[("two", "topic/one.md")] == "topic-one.md"
    mk.apply_migration(root, plan)
    entries = {e.id: e for e in store.load_report(root)[0]}
    assert "[two](two.md)" in entries["topic-one"].text
    assert "[gone](missing.md)" in entries["topic-one"].text
    assert "](topic-one.md#x)" in entries["two"].text


def test_migrate_knowledge_existing_file_with_other_content_is_collision(
    bundle, root
) -> None:
    first = mk.apply_migration(root, mk.plan_migration(bundle, root, KEY))
    victim = first.created[0]
    victim.write_text(victim.read_text() + "\nhuman edit\n", encoding="utf-8")
    plan = mk.plan_migration(bundle, root, KEY)
    assert len(plan.collisions) == 1 and len(plan.planned) == 7


def test_migrate_single_reader_follows_the_record(bundle, root) -> None:
    def ids() -> list[str]:
        entries, _ = sources.loader_for(root, bundle, scope_key=KEY)()
        return sorted(e.id for e in entries)

    from_bundle = ids()
    assert len(from_bundle) == 8
    mk.apply_migration(root, mk.plan_migration(bundle, root, KEY))
    assert ids() == from_bundle
    entries, _ = sources.loader_for(root, bundle, scope_key=KEY)()
    assert all(
        e.scope == "project" and e.source.startswith("knowledge:") for e in entries
    )
    assert len(entries) == 8
    mk.undo_migration(root, bundle)
    assert ids() == from_bundle
    loader = sources.loader_for(root, bundle, scope_key=KEY)
    assert getattr(loader, "func", None) is sources.load_bundle


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "mem"


def migrate(*argv: str) -> tuple[int, dict]:
    out = Io()
    code = cli_memory.run(["memory", "migrate", *argv, "--json"], out)
    text = out.stdout.getvalue() or out.stderr.getvalue()
    return code, json.loads(text)


def test_migrate_knowledge_cli_dry_run_apply_undo(bundle, cli_env, tmp_path) -> None:
    flags = ("--knowledge", str(bundle), "--project-root", str(tmp_path))
    code, body = migrate(*flags)
    data = body["data"]
    assert code == 0 and data["files"] == 8 and data["created"] == []
    assert files_under(cli_env) == []
    code, body = migrate(*flags, "--apply")
    assert code == 0 and len(body["data"]["created"]) == 8
    code, body = migrate(*flags, "--undo")
    assert code == 0 and len(body["data"]["removed"]) == 8
    assert [p for p in files_under(cli_env) if p.suffix == ".md"] == []


def test_migrate_knowledge_cli_rejects_bad_usage(bundle, cli_env) -> None:
    code, _ = migrate("--apply")
    assert code == 2
    code, _ = migrate("--knowledge", str(bundle), "--apply", "--undo")
    assert code == 2


def test_undo_keeps_the_record_for_changed_files(bundle, root) -> None:
    first = mk.apply_migration(root, mk.plan_migration(bundle, root, KEY))
    edited = first.created[0]
    original = edited.read_text()
    edited.write_text(original + "\nhuman edit\n", encoding="utf-8")
    undone = mk.undo_migration(root, bundle)
    assert undone.record_kept and not undone.record_removed
    record = migration_record.read_record(root, bundle)
    assert record is not None and list(record["created"]) == [str(edited)]
    edited.write_text(original, encoding="utf-8")
    again = mk.undo_migration(root, bundle)
    assert again.removed == [edited] and again.record_removed
    assert migration_record.read_record(root, bundle) is None


def test_undo_ignores_paths_outside_the_root(bundle, root, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    migration_record.write_record(
        root, bundle, {str(outside): mk.version(outside.read_bytes())}
    )
    undone = mk.undo_migration(root, bundle)
    assert undone.skipped == [outside] and outside.exists()
    assert undone.record_removed


def test_write_record_is_atomic(bundle, root, monkeypatch) -> None:
    migration_record.write_record(root, bundle, {"a": "1"})
    path = migration_record.record_path(root, bundle)

    def fail(*_args) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(migration_record.os, "replace", fail)
    with pytest.raises(OSError):
        migration_record.write_record(root, bundle, {"b": "2"})
    assert migration_record.read_record(root, bundle) == {
        "bundle": str(bundle.resolve()),
        "created": {"a": "1"},
    }
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_rewrite_links_is_one_pass_and_skips_code() -> None:
    body = "[a](x.md) [b](y.md)\n\n```\n[c](x.md)\n```\n"
    text, changes = mk.rewrite_links("n", body, {"x": "y", "y": "z"})
    assert text.startswith("[a](y.md) [b](z.md)")
    assert "[c](x.md)" in text
    assert [(c.link, c.target) for c in changes] == [("x.md", "y.md"), ("y.md", "z.md")]


def test_migrate_rejects_dry_run_with_apply(bundle, cli_env) -> None:
    code, _ = migrate("--knowledge", str(bundle), "--dry-run", "--apply")
    assert code == 2
