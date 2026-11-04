from pathlib import Path

from varde_code.rules import load_rules, loader, parse_pack_file


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pattern(rule_id: str, message: str = "rule") -> str:
    return f'''[[rule]]
id = "{rule_id}"
kind = "pattern"
severity = "warning"
message = "{message}"
pattern = "foo()"
'''


def test_parse_pack_file_keeps_valid_entries_and_reports_bad_entries(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "mixed.toml"
    _write(
        pack,
        _pattern("valid")
        + """
[[rule]]
id = "missing-pattern"
kind = "pattern"
severity = "warning"
message = "invalid"
""",
    )

    rules, diagnostics = parse_pack_file(pack)

    assert [rule.id for rule in rules] == ["valid"]
    assert diagnostics[0].rule_id == "missing-pattern"
    assert "requires a `pattern` field" in diagnostics[0].reason


def test_parse_pack_file_reports_invalid_toml(tmp_path: Path) -> None:
    pack = tmp_path / "broken.toml"
    _write(pack, "[[rule]\nid = ")

    rules, diagnostics = parse_pack_file(pack)

    assert rules == []
    assert len(diagnostics) == 1
    assert diagnostics[0].file == str(pack)
    assert diagnostics[0].reason.startswith("invalid TOML:")


def test_load_rules_orders_scopes_and_project_overrides_user_and_builtin(
    tmp_path: Path, monkeypatch
) -> None:
    user = tmp_path / "user"
    project = tmp_path / "repo"
    monkeypatch.setenv("VARDE_USER_RULES_DIR", str(user))
    monkeypatch.setenv(
        "VARDE_USER_OVERRIDES_FILE", str(tmp_path / "missing-overrides.toml")
    )
    _write(user / "a.toml", _pattern("shared", "user") + _pattern("user-only"))
    _write(project / ".varde-code/rules/shared.toml", _pattern("shared", "project"))
    builtins = (
        ("<builtin>/shared.toml", _pattern("shared", "builtin")),
        ("<builtin>/built-in-only.toml", _pattern("builtin-only")),
    )

    rules, diagnostics = load_rules(project, builtins=builtins)

    assert [(rule.id, rule.message) for rule in rules] == [
        ("shared", "project"),
        ("user-only", "rule"),
        ("builtin-only", "rule"),
    ]
    assert diagnostics == []


def test_duplicate_ids_within_scope_keep_first_and_report(
    tmp_path: Path, monkeypatch
) -> None:
    user = tmp_path / "user"
    monkeypatch.setenv("VARDE_USER_RULES_DIR", str(user))
    monkeypatch.setenv(
        "VARDE_USER_OVERRIDES_FILE", str(tmp_path / "missing-overrides.toml")
    )
    _write(user / "a.toml", _pattern("same", "first"))
    _write(user / "b.toml", _pattern("same", "second"))

    rules, diagnostics = load_rules(tmp_path / "repo", builtins=())

    assert [rule.message for rule in rules] == ["first"]
    assert len(diagnostics) == 1
    assert diagnostics[0].file == str(user / "b.toml")
    assert "duplicate rule id `same` in user scope" in diagnostics[0].reason


def test_discover_sorts_toml_files_and_ignores_other_files(tmp_path: Path) -> None:
    user = tmp_path / "user"
    repo = tmp_path / "repo"
    _write(user / "z.toml", "")
    _write(user / "a.toml", "")
    _write(user / "readme.md", "ignored")
    _write(repo / ".varde-code/rules/b.toml", "")

    files, diagnostics = loader.discover(repo, user)

    assert [(item.scope, item.path.name) for item in files] == [
        ("user", "a.toml"),
        ("user", "z.toml"),
        ("project", "b.toml"),
    ]
    assert diagnostics == []


def test_seed_and_remove_preserve_customized_pack_unless_forced(
    tmp_path: Path, monkeypatch
) -> None:
    packs = (("<builtin>/sample.toml", _pattern("sample")),)
    monkeypatch.setattr(loader, "_builtin_packs", lambda: packs)
    target = tmp_path / "seeded"

    seeded = loader.seed_builtin_rules(target)
    assert len(seeded) == 1 and seeded[0].written
    assert loader.seed_builtin_rules(target)[0].skipped_existing
    seeded[0].path.write_text("customized", encoding="utf-8")

    removed = loader.remove_builtin_rules(target)
    assert len(removed) == 1 and removed[0].skipped_modified
    assert seeded[0].path.exists()
    forced = loader.remove_builtin_rules(target, force=True)
    assert len(forced) == 1 and forced[0].removed
    assert not seeded[0].path.exists()


def test_loader_parses_valid_tests_and_reports_malformed_or_kind_mismatched_entries(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "pack.toml"
    _write(
        pack,
        """
[[rule]]
id = "sql-rule"
kind = "sql"
severity = "warning"
message = "found"
query = "SELECT 1"

[[rule.test]]
name = "valid"
fixture = { "files/a.py" = "pass" }
expect_rows = [{ "count" = 1 }]

[[rule.test]]
name = "wrong-kind"
valid = ["x"]

[[rule.test]]
fixture = { "files/a.py" = "pass" }
""",
    )

    rules, diagnostics = parse_pack_file(pack)

    assert rules[0].test is not None
    assert [case.name for case in rules[0].test] == ["valid"]
    assert len(diagnostics) == 2
    assert "only valid on kind=pattern" in diagnostics[0].reason
    assert diagnostics[1].reason.startswith("malformed [[test]] entry:")


def test_user_rules_dir_uses_code_config_and_legacy_until_marker(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.delenv("VARDE_CODE_USER_RULES_DIR", raising=False)
    monkeypatch.delenv("VARDE_USER_RULES_DIR", raising=False)

    assert loader.user_rules_dir() == Path.home() / ".config" / "varde-code" / "rules"
    marker = config / "code" / ".varde-migration-complete"
    marker.parent.mkdir(parents=True)
    marker.touch()
    assert loader.user_rules_dir() == config / "code" / "rules"
