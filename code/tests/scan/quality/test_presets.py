"""Quality rule ids in presets and the lenient override reason."""

import tomllib

import pytest
from varde_code.query.params import QueryError
from varde_code.rules import loader
from varde_code.scan import setup

GATE = ("quality-file-floor", "quality-function-cap", "quality-scope-mean")


def test_quality_gate_ids_join_presets():
    assert all(rule_id in setup.PRESET_RULE_IDS for rule_id in GATE)


def test_strict_raises_mean_and_minimal_turns_gate_off():
    strict = tomllib.loads(setup.overrides_toml("strict") or "")["rules"]
    assert all(strict[rule_id]["severity"] == "error" for rule_id in GATE)
    minimal = tomllib.loads(setup.overrides_toml("minimal") or "")["rules"]
    assert all(minimal[rule_id]["severity"] == "off" for rule_id in GATE)


def test_lenient_requires_reason():
    for reason in (None, "", "   "):
        with pytest.raises(QueryError, match="requires a non-empty reason"):
            setup.overrides_toml("lenient", reason)


def test_lenient_lowers_only_floor_and_cap_with_reason():
    text = setup.overrides_toml("lenient", "legacy debt", "2026-10-31", "2027-01-31")
    rules = tomllib.loads(text or "")["rules"]
    assert set(rules) == {"quality-file-floor", "quality-function-cap"}
    for entry in rules.values():
        assert entry == {
            "severity": "warning",
            "reason": "legacy debt",
            "date": "2026-10-31",
            "review_by": "2027-01-31",
        }


def test_lenient_reason_is_quoted_safely():
    text = setup.overrides_toml("lenient", 'say "hi"\nok')
    rules = tomllib.loads(text or "")["rules"]
    assert rules["quality-file-floor"]["reason"] == 'say "hi"\nok'


def test_setup_run_lenient_refuses_without_reason_and_writes_with(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(QueryError, match="reason"):
        setup.run({"repoRoot": str(tmp_path), "preset": "lenient"})
    assert not (tmp_path / ".varde-code" / "overrides.toml").exists()
    result = setup.run(
        {"repoRoot": str(tmp_path), "preset": "lenient", "reason": "legacy"}
    )
    assert result["written"] is not None
    rules, _, details = loader.load_rules_with_details(tmp_path)
    by_id = {rule.id: rule for rule in rules}
    assert by_id["quality-file-floor"].severity.value == "warning"
    assert by_id["quality-scope-mean"].severity.value == "warning"
    assert not details.orphaned_overrides
