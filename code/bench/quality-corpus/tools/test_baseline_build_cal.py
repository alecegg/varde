# ruff: noqa: S101
"""Finalize rules for cal-1 validation states (pure, no I/O beyond tmp files)."""

import baseline_build_cal as bc
import pytest

PASS_Q = {
    f"{lang}:{q}": {"pass": True, "rate": 1.0}
    for lang in bc.LANGUAGES
    for q in ("q4", "q5")
}
OK_CONSTRAINTS = {
    "verdict": {
        lang: {"tune_check": "pass", "mutations": "pass"} for lang in bc.LANGUAGES
    }
}
AGREED = {
    f"{lang}/p{i}": {"language": lang, "agreed": True}
    for lang in bc.LANGUAGES
    for i in range(4)
}
TEXT = "validated = false\n" + "".join(
    f"[language.{lang}.validation]\n"
    'state = "report-only"\nreason = "pending constraints"\nprovenance = "x"\n'
    for lang in bc.LANGUAGES
)


def decide(constraints=OK_CONSTRAINTS, q4q5=PASS_Q, agreement=AGREED, verdict="PASS"):
    return bc.decide_states(constraints, q4q5, agreement, verdict)


def test_all_conditions_hold_validates_every_language():
    states = decide()
    assert {s for s, _ in states.values()} == {bc.VALIDATED}
    assert "validated = true" in bc.apply_states(TEXT, states)


def test_missing_or_failing_resolver_verdict_is_report_only_with_reason():
    assert decide(verdict=None)["python"] == (
        bc.REPORT_ONLY,
        "resolver verdict missing",
    )
    assert decide(verdict="FAIL: gaps")["python"][1] == "resolver verdict not PASS"


def test_each_unmet_condition_is_named_and_validated_stays_false():
    constraints = {
        "verdict": {**OK_CONSTRAINTS["verdict"], "csharp": {"tune_check": "FAIL"}}
    }
    q4q5 = {**PASS_Q, "typescript:q5": {"pass": False, "rate": 0.8333}}
    agreement = {k: v for k, v in AGREED.items() if not k.startswith("csharp")}
    states = decide(constraints, q4q5, agreement)
    assert states["python"][0] == bc.VALIDATED
    assert states["typescript"] == (bc.REPORT_ONLY, "Q5 0.8333 below threshold")
    assert "constraints tune check FAIL" in states["csharp"][1]
    assert "agreement 0/3 agreed cells" in states["csharp"][1]
    assert "validated = false" in bc.apply_states(TEXT, states)


def test_apply_then_reset_round_trips_and_unknown_table_raises():
    states = decide(verdict=None)
    assert bc.reset_states(bc.apply_states(TEXT, states)) == TEXT
    with pytest.raises(ValueError):
        bc.apply_states("validated = false\n", states)
