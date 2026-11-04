from varde_design.registry import PROFILES, RULES, RULES_BY_ID, active_rules, rule_ids


def test_registry_has_the_eighteen_starting_rules() -> None:
    expected = [f"S{n}" for n in range(1, 11)] + [f"R{n}" for n in range(1, 9)]
    assert list(rule_ids()) == expected
    assert len(RULES_BY_ID) == len(RULES) == 18


OPINION_IDS = {"S1", "S3", "S7", "S8", "S9", "S10", "R4", "R7"}


def test_opinion_rules_are_the_labelled_low_precision_ones() -> None:
    opinion = {rule.id for rule in RULES if rule.profile == "opinion"}
    assert opinion == OPINION_IDS


def test_core_profile_is_ten_rules_and_opinion_adds_the_rest() -> None:
    core = {rule.id for rule in active_rules("core")}
    assert core == set(rule_ids()) - OPINION_IDS
    assert len(core) == 10
    assert {rule.id for rule in active_rules("opinion")} == set(rule_ids())


def test_only_rules_over_the_precision_bar_can_fail() -> None:
    fail = {rule.id for rule in RULES if rule.severity == "fail"}
    assert fail == {"S6", "R1", "R2", "R6"}


def test_gate_rules_are_the_universal_defects() -> None:
    assert {rule.id for rule in RULES if rule.gate} == {"R1", "R2", "R3", "R6"}


def test_rule_fields_are_valid() -> None:
    for rule in RULES:
        assert rule.severity in {"fail", "warn"}
        assert rule.tier in {"static", "rendered", "both"}
        assert rule.profile in PROFILES
        assert rule.id[0] == ("S" if rule.tier == "static" else rule.id[0])
        assert rule.summary


def test_unknown_profile_is_rejected() -> None:
    try:
        active_rules("strict")
    except ValueError as error:
        assert "strict" in str(error)
    else:
        raise AssertionError("expected ValueError")
