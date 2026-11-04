from __future__ import annotations

import tomllib

import pytest
from varde_code.query.params import QueryError
from varde_code.rules import loader
from varde_code.scan import rules_cmd, setup


def test_rules_list_returns_loaded_rule_metadata_without_an_index(tmp_path):
    result = rules_cmd.run("list", {"repoRoot": str(tmp_path)})

    assert result["rules"]
    builtin = next(rule for rule in result["rules"] if rule["source"] == "builtin")
    assert "severitySource" in builtin
    assert isinstance(builtin["drifted"], bool)
    assert "diagnostics" in result
    assert "orphanedOverrides" in result


def test_rules_seed_remove_and_diff_reuse_loader(tmp_path, monkeypatch):
    root_input = {"repoRoot": str(tmp_path)}
    seeded = rules_cmd.run("seed", root_input)
    assert seeded["seeded"] is not None
    assert seeded["seeded"]
    assert seeded["targetDir"] == ".varde-code/rules"
    first_path = tmp_path / seeded["seeded"][0]["path"]
    assert first_path is not None
    with open(first_path, encoding="utf-8") as pack:
        assert tomllib.loads(pack.read())
    skipped = rules_cmd.run("seed", root_input)
    skipped_rules = skipped["seeded"]
    assert skipped_rules is not None
    assert all(item["skippedExisting"] for item in skipped_rules)

    pack = loader.builtin_rule_pack_for("eval-usage")
    assert pack is not None
    pack_label, pack_text = pack
    seed_path = tmp_path / ".varde-code" / "rules" / pack_label.rsplit("/", 1)[-1]
    seed_path.write_text(
        pack_text.replace('severity = "error"', 'severity = "warning"', 1),
        encoding="utf-8",
    )
    diff = rules_cmd.run("diff", {**root_input, "ruleId": "eval-usage"})
    assert diff["ruleId"] == "eval-usage"
    assert diff["seedScope"] == "repo"
    assert "--- a/" in diff["diff"]
    assert "+++ b/" in diff["diff"]

    removed = rules_cmd.run("remove", root_input)
    assert removed["targetDir"] == ".varde-code/rules"
    assert any(item["skippedModified"] for item in removed["removed"])
    forced = rules_cmd.run("remove", root_input, force=True)
    assert any(item["removed"] for item in forced["removed"])

    user_dir = tmp_path / "user-rules"
    monkeypatch.setenv("VARDE_CODE_USER_RULES_DIR", str(user_dir))
    user_seeded = rules_cmd.run("seed", root_input, user=True)
    assert user_seeded["targetDir"] == "user-rules"
    assert all(item["path"].startswith("user-rules/") for item in user_seeded["seeded"])
    user_removed = rules_cmd.run("remove", root_input, user=True, force=True)
    assert user_removed["targetDir"] == "user-rules"
    assert all(
        item["path"].startswith("user-rules/") for item in user_removed["removed"]
    )


def test_rules_diff_validation_and_missing_repo(tmp_path):
    with pytest.raises(QueryError, match="ruleId is required"):
        rules_cmd.run("diff", {"repoRoot": str(tmp_path)})
    with pytest.raises(QueryError, match="unknown built-in rule id"):
        rules_cmd.run("diff", {"repoRoot": str(tmp_path), "ruleId": "missing"})
    with pytest.raises(QueryError, match="repoRoot is not a directory"):
        rules_cmd.run("list", {"repoRoot": str(tmp_path / "missing")})


def test_setup_presets_render_and_filter_languages(tmp_path):
    rendered = setup.overrides_toml("minimal")
    assert rendered is not None
    parsed = tomllib.loads(rendered)
    assert len(parsed["rules"]) == len(setup.PRESET_RULE_IDS)
    assert all(item["severity"] == "off" for item in parsed["rules"].values())
    assert setup.overrides_toml("balanced") is None
    with pytest.raises(QueryError, match="unknown preset"):
        setup.overrides_toml("unknown")

    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    rules, _, _ = loader.load_rules_with_details(tmp_path)
    filtered = setup.filter_rules(rules, ["python"])
    assert any(rule.kind.value == "sql" for rule in filtered)
    assert all(
        not rule.languages
        or any(
            (parsed := setup.language_from_name(language.lower())) is not None
            and setup.language_name(parsed) == "python"
            for language in rule.languages
        )
        for rule in filtered
        if rule.kind.value != "sql"
    )


def test_setup_writes_preset_and_refuses_overwrite_without_force(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    result = setup.run({"repoRoot": str(tmp_path), "preset": "minimal"})
    assert result["detectedLanguages"] == ["python"]
    assert result["written"] == str(tmp_path / ".varde-code" / "overrides.toml")
    assert (tmp_path / ".varde-code" / "overrides.toml").is_file()
    with pytest.raises(QueryError, match="pass --force to overwrite"):
        setup.run({"repoRoot": str(tmp_path), "preset": "strict"})
    forced = setup.run({"repoRoot": str(tmp_path), "preset": "strict", "force": True})
    assert forced["written"] == result["written"]
    balanced = setup.run({"repoRoot": str(tmp_path), "preset": "balanced"})
    assert balanced["written"] is None
    assert balanced["message"].startswith("Balanced leaves")


def test_setup_keeps_disabled_applicable_rules_at_the_end(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    setup.run({"repoRoot": str(tmp_path), "preset": "minimal"})

    result = setup.run({"repoRoot": str(tmp_path), "preset": "minimal", "force": True})
    rules = result["effectiveRules"]
    present_ids = {rule["id"] for rule in rules}
    disabled_ids = [
        rule_id for rule_id in setup.PRESET_RULE_IDS if rule_id in present_ids
    ]

    assert disabled_ids
    assert [rule["id"] for rule in rules[-len(disabled_ids) :]] == disabled_ids
