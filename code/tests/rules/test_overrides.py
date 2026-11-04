from pathlib import Path

import pytest
from varde_code.rules import loader
from varde_code.rules.model import Severity


def _pack(rule_id: str, severity: str = "warning") -> str:
    return f'''[[rule]]
id = "{rule_id}"
kind = "pattern"
severity = "{severity}"
message = "{rule_id}"
pattern = "foo()"
'''


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_overrides_prefer_repo_and_track_disabled_and_orphaned(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VARDE_USER_RULES_DIR", str(tmp_path / "user-rules"))
    user_overrides = tmp_path / "user-overrides.toml"
    monkeypatch.setenv("VARDE_USER_OVERRIDES_FILE", str(user_overrides))
    repo = tmp_path / "repo"
    _write(
        user_overrides,
        (
            '[rules."builtin-rule"]\nseverity = "info"\n'
            '[rules."ghost"]\nseverity = "off"\n'
        ),
    )
    _write(
        repo / ".varde-code/overrides.toml",
        (
            '[rules."builtin-rule"]\nseverity = "off"\n'
            '[rules."custom-rule"]\nseverity = "error"\n'
        ),
    )
    _write(repo / ".varde-code/rules/custom.toml", _pack("custom-rule"))
    builtins = (("<builtin>/sample.toml", _pack("builtin-rule")),)

    rules, diagnostics, details = loader.load_rules_with_details(
        repo, builtins=builtins
    )

    assert [(rule.id, rule.severity) for rule in rules] == [
        ("custom-rule", Severity.ERROR)
    ]
    assert diagnostics == []
    assert details.origins == {"custom-rule": "override"}
    assert details.severity_sources == {"custom-rule": "repo-override"}
    assert [
        (item.rule.id, item.severity_source) for item in details.disabled_rules
    ] == [("builtin-rule", "repo-override")]
    assert [
        (item.rule_id, item.source, item.severity)
        for item in details.orphaned_overrides
    ] == [("ghost", "user-override", "off")]


def test_invalid_override_entries_are_diagnostics(tmp_path: Path, monkeypatch) -> None:
    override_file = tmp_path / "overrides.toml"
    monkeypatch.setenv("VARDE_CODE_USER_OVERRIDES_FILE", str(override_file))
    monkeypatch.setenv("VARDE_USER_RULES_DIR", str(tmp_path / "user-rules"))
    _write(override_file, '[rules."bad"]\nseverity = "fatal"\n[rules."missing"]\n')

    _, diagnostics, _ = loader.load_rules_with_details(tmp_path / "repo", builtins=())

    assert len(diagnostics) == 2
    assert "invalid severity `fatal`" in diagnostics[0].reason
    assert "must include a string `severity`" in diagnostics[1].reason


def test_seed_one_builtin_pack_and_report_unknown_id(
    tmp_path: Path, monkeypatch
) -> None:
    packs = (
        ("<builtin>/first.toml", _pack("first")),
        ("<builtin>/second.toml", _pack("second")),
    )
    monkeypatch.setattr(loader, "_builtin_packs", lambda: packs)

    results = loader.seed_builtin_rules_for(tmp_path / "rules", rule_id="second")

    assert [item.file_name for item in results] == ["second.toml"]
    assert results[0].written
    assert loader.builtin_rule_pack_for("second") == packs[1]
    with pytest.raises(ValueError, match="unknown built-in rule id: missing"):
        loader.seed_builtin_rules_for(tmp_path / "rules", rule_id="missing")


def test_seed_io_errors_are_not_silently_swallowed(tmp_path: Path, monkeypatch) -> None:
    packs = (("<builtin>/first.toml", _pack("first")),)
    monkeypatch.setattr(loader, "_builtin_packs", lambda: packs)
    target = tmp_path / "rules"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError):
        loader.seed_builtin_rules(target)

    # An invalid UTF-8 seeded file is the Python equivalent of Rust's
    # read_to_string InvalidData error during unseed.
    seeded = tmp_path / "sample.toml"
    seeded.write_bytes(b"\xff")
    monkeypatch.setattr(
        loader, "_builtin_packs", lambda: (("<builtin>/sample.toml", _pack("sample")),)
    )
    with pytest.raises(OSError, match="invalid UTF-8"):
        loader.remove_builtin_rules(tmp_path)


def test_builtin_helpers_report_pack_contents_and_detect_seed_drift(
    tmp_path: Path, monkeypatch
) -> None:
    builtin = _pack("sample")
    packs = (("<builtin>/sample.toml", builtin),)
    monkeypatch.setattr(loader, "_builtin_packs", lambda: packs)
    seeded = tmp_path / "sample.toml"
    _write(seeded, _pack("sample", "error"))

    assert [rule.id for rule in loader.builtin_rules()] == ["sample"]
    assert loader.builtin_rule_pack_for("sample") == packs[0]
    assert loader.seed_drifted("sample", str(seeded))
    assert not loader.seed_drifted("unknown", str(seeded))


def test_user_override_default_uses_code_config_dir(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("VARDE_CODE_USER_OVERRIDES_FILE", raising=False)
    monkeypatch.delenv("VARDE_USER_OVERRIDES_FILE", raising=False)

    assert (
        loader.overrides.user_overrides_file()
        == tmp_path / "config" / "code" / "overrides.toml"
    )

    legacy = tmp_path / "home" / ".config" / "varde-code"
    legacy.mkdir(parents=True)
    assert loader.overrides.user_overrides_file() == legacy / "overrides.toml"
    marker = tmp_path / "config" / "code" / ".varde-migration-complete"
    marker.parent.mkdir(parents=True)
    marker.touch()
    assert (
        loader.overrides.user_overrides_file()
        == tmp_path / "config" / "code" / "overrides.toml"
    )


def test_load_overrides_file_diagnostic_for_malformed_toml(
    tmp_path: Path, monkeypatch
) -> None:
    override_file = tmp_path / "broken.toml"
    monkeypatch.setenv("VARDE_USER_OVERRIDES_FILE", str(override_file))
    monkeypatch.setenv("VARDE_USER_RULES_DIR", str(tmp_path / "user-rules"))
    _write(override_file, "[rules\n")

    _, diagnostics, _ = loader.load_rules_with_details(tmp_path / "repo", builtins=())

    assert len(diagnostics) == 1
    assert diagnostics[0].file == str(override_file)
    assert diagnostics[0].reason.startswith("invalid TOML overrides file:")
