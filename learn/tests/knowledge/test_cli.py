import json
from pathlib import Path

import pytest
from varde_learn.knowledge.occ import version
from varde_learn.module import register


def _concept(body: str = "body\n") -> bytes:
    return (
        f"---\ntype: decision\ntitle: A decision\n"
        f"description: A decision document.\n---\n{body}"
    ).encode()


def test_module_contract_and_usage_error(capsys) -> None:
    module = register()
    assert module.name == "learn"
    assert module.run(["knowledge", "create"], io=None) == 2
    assert "Usage:" in capsys.readouterr().err


def test_concept_create_list_and_show_use_routed_argv(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    source = tmp_path / "example.md"
    source.write_bytes(_concept())
    module = register()

    assert (
        module.run(
            [
                "knowledge",
                "create",
                "--bundle",
                str(bundle),
                "--file",
                str(source),
                "--json",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["ok"] is True
    assert (bundle / "example.md").is_file()

    assert module.run(["knowledge", "search", "--bundle", str(bundle), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["data"] == [{"slug": "example", "type": "decision"}]

    assert (
        module.run(
            [
                "knowledge",
                "show",
                "--bundle",
                str(bundle),
                "example",
                "--frontmatter-only",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "type": "decision",
        "title": "A decision",
        "description": "A decision document.",
    }


def test_two_document_bundle_search_update_and_delete(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    module = register()
    for slug, title in (("example", "A decision"), ("second", "Another decision")):
        source = tmp_path / f"{slug}.md"
        source.write_bytes(_concept(f"{title}\n"))
        assert (
            module.run(
                [
                    "knowledge",
                    "create",
                    "--bundle",
                    str(bundle),
                    "--file",
                    str(source),
                    "--json",
                ]
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["data"]["slug"] == slug

    assert module.run(["knowledge", "search", "--bundle", str(bundle), "--json"]) == 0
    assert [item["slug"] for item in json.loads(capsys.readouterr().out)["data"]] == [
        "example",
        "second",
    ]
    assert (
        module.run(
            [
                "knowledge",
                "search",
                "--bundle",
                str(bundle),
                "--text",
                "decision",
                "--json",
            ]
        )
        == 0
    )
    hits = json.loads(capsys.readouterr().out)["data"]
    assert [hit["slug"] for hit in hits] == ["example", "second"]

    original = (bundle / "example.md").read_bytes()
    source = tmp_path / "updated.md"
    replacement = _concept("Updated decision\n")
    source.write_bytes(replacement)
    assert (
        module.run(
            [
                "knowledge",
                "update",
                "--bundle",
                str(bundle),
                "example",
                "--expected-version",
                version(original),
                "--file",
                str(source),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["slug"] == "example"
    assert "Updated decision" in (bundle / "example.md").read_text()

    assert (
        module.run(["knowledge", "delete", "--bundle", str(bundle), "second", "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"] == {
        "slug": "second",
        "deleted": True,
    }
    assert (
        module.run(
            ["knowledge", "delete", "--bundle", str(bundle), "missing", "--json"]
        )
        == 2
    )
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "data", [b"plain text\n", b"---\ntitle: [\n---\n", b"---\n- item\n---\n"]
)
def test_concept_create_frontmatter_errors_use_internal_json_code(
    tmp_path: Path, capsys, data: bytes
) -> None:
    source = tmp_path / "example.md"
    source.write_bytes(data)

    assert (
        register().run(
            [
                "knowledge",
                "create",
                "--bundle",
                str(tmp_path / "bundle"),
                "--file",
                str(source),
                "--json",
            ]
        )
        == 1
    )
    error = json.loads(capsys.readouterr().err.splitlines()[-1])  # after the notice
    assert error["ok"] is False
    assert error["data"]["error"]["code"] == "internal"


def test_lint_error_exit_passes_through_module_run(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    (bundle / "a.md").write_bytes(_concept("[missing](/missing.md)\n"))

    assert register().run(["knowledge", "lint", "--bundle", str(bundle)]) == 1
    assert capsys.readouterr().out.startswith("error:")


def test_lint_reports_broken_link_and_accepts_valid_doc(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    (bundle / "bad.md").write_bytes(_concept("[missing](/missing.md)\n"))
    assert register().run(["knowledge", "lint", "--bundle", str(bundle)]) == 1
    assert "missing.md" in capsys.readouterr().out

    (bundle / "bad.md").unlink()
    (bundle / "good.md").write_bytes(_concept())
    assert register().run(["knowledge", "lint", "--bundle", str(bundle)]) == 0
    assert capsys.readouterr().out.startswith("warning:")


def test_create_rejects_invalid_frontmatter_field_with_named_error(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "invalid.md"
    source.write_text("---\ntype: decision\ndescription: ''\n---\nbody\n")
    status = register().run(
        [
            "knowledge",
            "create",
            "--bundle",
            str(tmp_path / "knowledge"),
            "--file",
            str(source),
        ]
    )
    assert status == 4
    assert "description" in capsys.readouterr().err


def test_paths_set_and_show_with_json(tmp_path: Path, monkeypatch, capsys) -> None:
    config_dir = tmp_path / "config"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    module = register()

    assert (
        module.run(
            ["paths", "set", "--project", str(project), "--working", "notes", "--json"]
        )
        == 0
    )
    updated = json.loads(capsys.readouterr().out)
    assert updated["data"]["working"] == str(project / "notes")

    assert module.run(["paths", "--project", str(project), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["data"]["working"] == str(project / "notes")


def test_set_field_uses_expected_version(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    original = _concept()
    (bundle / "example.md").write_bytes(original)

    assert (
        register().run(
            [
                "knowledge",
                "set-field",
                "--bundle",
                str(bundle),
                "example",
                "status",
                "stable",
                "--expected-version",
                version(original),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["data"]["key"] == "status"
    assert "status: stable" in (bundle / "example.md").read_text()


def test_map_writes_root_and_type_maps(tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    (bundle / "example.md").write_bytes(_concept())

    assert register().run(["knowledge", "map", "--bundle", str(bundle), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["root"] == "index.md"
    assert data["entries"] == 1
    assert (bundle / "index.md").is_file()
    assert (bundle / data["type_maps"][0]).is_file()


@pytest.fixture
def alias_env(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.chdir(tmp_path)
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    (bundle / "postgres-notes.md").write_bytes(_concept("postgres tuning\n"))
    return bundle


def test_alias_notice_on_stderr_and_stdout_unchanged(alias_env, capsys) -> None:
    module = register()
    argv = ["knowledge", "search", "--bundle", str(alias_env), "--text", "postgres"]
    assert module.run([*argv, "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)["data"]
    assert [item["slug"] for item in data] == ["postgres-notes"]
    assert "deprecated" in captured.err and "memory search" in captured.err
    assert "deprecated" not in captured.out


def test_alias_notice_names_add_for_create(alias_env, capsys) -> None:
    module = register()
    assert module.run(["knowledge", "show", "--bundle", str(alias_env), "x"]) != 0
    assert "`varde learn memory show`" in capsys.readouterr().err


def test_alias_reads_migrated_bundle_from_unified_store_once(
    alias_env, capsys, tmp_path
) -> None:
    from varde_learn.memory import migrate_knowledge as mk
    from varde_learn.memory import store

    root = store.memory_root(tmp_path)
    key = "repo-0123456789abcdef"
    mk.apply_migration(root, mk.plan_migration(alias_env, root, key))
    module = register()
    argv = ["knowledge", "search", "--bundle", str(alias_env), "--text", "postgres"]
    assert module.run([*argv, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [item["slug"] for item in data] == ["postgres-notes"]
    (alias_env / "postgres-notes.md").unlink()  # the bundle is no longer read
    assert module.run([*argv, "--json"]) == 0
    assert [i["slug"] for i in json.loads(capsys.readouterr().out)["data"]] == [
        "postgres-notes"
    ]


def _bundle_with(tmp_path: Path, project: str, slugs: list[str]) -> Path:
    bundle = tmp_path / project / "knowledge"
    bundle.mkdir(parents=True)
    for slug in slugs:
        (bundle / f"{slug}.md").write_bytes(_concept("zebra herd\n"))
    return bundle


def test_alias_search_does_not_leak_other_bundles(alias_env, capsys, tmp_path) -> None:
    from varde_learn.memory import migrate_knowledge as mk
    from varde_learn.memory import store

    root = store.memory_root(tmp_path)
    first = _bundle_with(tmp_path, "a", ["note-pa"])
    second = _bundle_with(tmp_path, "b", ["note-pb"])
    mk.apply_migration(root, mk.plan_migration(first, root, "a-0123456789abcdef"))
    mk.apply_migration(root, mk.plan_migration(second, root, "b-0123456789abcdef"))
    argv = ["knowledge", "search", "--bundle", str(first), "--text", "zebra", "--json"]
    assert register().run(argv) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [item["slug"] for item in data] == ["note-pa"]


def test_alias_show_reads_the_store_after_migration(
    alias_env, capsys, tmp_path
) -> None:
    from dataclasses import replace

    from varde_learn.memory import migrate_knowledge as mk
    from varde_learn.memory import store

    root = store.memory_root(tmp_path)
    plan = mk.plan_migration(alias_env, root, "repo-0123456789abcdef")
    mk.apply_migration(root, plan)
    entry = plan.planned[0].entry
    store.write_entry(root, replace(entry, text="edited in store\n"), overwrite=True)
    argv = ["knowledge", "show", "--bundle", str(alias_env), "postgres-notes", "--json"]
    assert register().run(argv) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["body"].strip() == "edited in store"
    assert data["frontmatter"]["type"] == "decision"


def test_alias_notice_points_paths_to_setup_and_skips_unknown_verbs(
    alias_env, capsys
) -> None:
    module = register()
    module.run(["knowledge", "paths"])
    assert "varde setup paths" in capsys.readouterr().err
    assert module.run(["knowledge", "bogus"]) != 0
    assert "deprecated" not in capsys.readouterr().err


def test_alias_refuses_to_edit_a_migrated_bundle(alias_env, capsys, tmp_path) -> None:
    from varde_learn.memory import migrate_knowledge as mk
    from varde_learn.memory import store

    root = store.memory_root(tmp_path)
    mk.apply_migration(
        root, mk.plan_migration(alias_env, root, "repo-0123456789abcdef")
    )
    module = register()
    code = module.run(
        ["knowledge", "delete", "--bundle", str(alias_env), "postgres-notes"]
    )
    assert code != 0
    assert "migrated" in capsys.readouterr().err
    assert (alias_env / "postgres-notes.md").exists()


def test_setup_paths_memory_flag_sets_and_unsets_default(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("VARDE_MEMORY_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    module = register()
    target = str(tmp_path / "agent-memory" / "memory")
    assert module.run(["paths", "set", "--memory", target, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["default"]["memory"] == target
    assert module.run(["paths", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["memory"] == target
    assert module.run(["paths", "unset", "--memory", "--json"]) == 0
    assert "memory" not in json.loads(capsys.readouterr().out)["data"]["default"]
    assert module.run(["paths", "set", "--memory", target, "--working", "w"]) == 1
    assert "only with --default" in capsys.readouterr().err
    assert "--memory" in _help_set()


def _help_set() -> str:
    from varde_learn.knowledge.cli import help_text

    return help_text("paths set")
