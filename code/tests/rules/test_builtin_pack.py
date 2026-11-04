from pathlib import Path

from varde_code.rules import load_rules, loader

BUILTIN_RULE_PACKS = (
    "quality_gate.toml",
    "complexity.toml",
    "empty_catch_block.toml",
    "eval_usage.toml",
    "duplicate_code_clone.toml",
    "debug_statement_strict.toml",
    "hardcoded_credential_literal.toml",
    "low_fan_in_high_fan_out_file.toml",
    "circular_import.toml",
    "unresolved_local_import.toml",
    "vertical_slice_sprawl.toml",
    "solid.toml",
    "dependency_boundary.toml",
    "hardcoded_credential_rust.toml",
    "hardcoded_credential_go.toml",
    "hardcoded_credential_jvm_dotnet.toml",
    "hardcoded_credential_native_apple.toml",
    "hardcoded_credential_native_apple_class.toml",
    "hardcoded_credential_scripting.toml",
    "hardcoded_credential_other.toml",
    "error_swallow_rust.toml",
    "error_swallow_go.toml",
    "error_swallow_c_scala_solidity.toml",
    "error_swallow_lua_bash.toml",
    "error_swallow_elixir_haskell.toml",
)


def test_builtin_pack_list_loads_without_diagnostics(
    tmp_path: Path, monkeypatch
) -> None:
    pack_dir = Path(loader.__file__).parent / "builtin"
    assert tuple(path.name for path in sorted(pack_dir.glob("*.toml"))) == tuple(
        sorted(BUILTIN_RULE_PACKS)
    )
    assert loader.BUILTIN_PACK_NAMES == BUILTIN_RULE_PACKS
    monkeypatch.setenv("VARDE_USER_RULES_DIR", str(tmp_path / "user-rules"))

    rules, diagnostics = load_rules(tmp_path)

    assert len(rules) == 144
    assert diagnostics == []
