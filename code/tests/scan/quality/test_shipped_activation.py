"""The calibration that scan ships drives each language's effective severity.

Reads the real calibration (not a fixture): a language gates only when its shipped
state is panel- or baseline-validated; every other language is capped at ``info``
and labelled ``not validated``. The expected values come from the calibration, so
the test stays true as calibration validates languages (loop route R3).
"""

from __future__ import annotations

import pytest
from varde_code.model import Span
from varde_code.quality_score.calibration import (
    load_calibration,
    shipped_calibration_path,
)
from varde_code.rules.finding import Finding, Location
from varde_code.rules.model import Severity
from varde_code.scan import quality_wiring
from varde_code.scan.quality_mode import NOT_VALIDATED_LABEL
from varde_code.scan.quality_scores import LANGUAGE_FALLBACKS

V1_LANGUAGES = ("python", "typescript", "csharp")
GATE_RULES = ("quality-file-floor", "quality-function-cap", "quality-scope-mean")


@pytest.fixture(scope="module")
def shipped():
    return load_calibration(shipped_calibration_path())


def _finding(rule_id: str, language: str) -> Finding:
    span = Span(0, 0, 1, 0, 1, 0)
    return Finding(
        f"id-{rule_id}", rule_id, Severity.ERROR, "m",
        Location("a", span), {"language": language}, None,
    )  # fmt: skip


def test_scan_loads_the_shipped_calibration_not_the_placeholder(shipped):
    assert "placeholder" not in shipped.id
    assert shipped.id == "cal-2"


@pytest.mark.parametrize("language", V1_LANGUAGES)
def test_shipped_state_drives_effective_severity(shipped, language):
    state_of = quality_wiring.calibration_state_lookup(shipped)
    gating = shipped.language_gating_available(language)
    findings = [_finding(rule, language) for rule in GATE_RULES]

    moded = quality_wiring.apply_quality_mode(findings, state_of, [language])

    for finding in moded:
        if gating:
            assert finding.severity is Severity.ERROR
            assert "quality_mode" not in finding.evidence
        else:
            assert finding.severity is Severity.INFO
            assert finding.evidence["quality_mode"] == NOT_VALIDATED_LABEL


@pytest.mark.parametrize("language", V1_LANGUAGES)
def test_a_non_gating_language_names_its_unmet_requirement(shipped, language):
    entry = shipped.languages[language]
    if shipped.language_gating_available(language):
        return
    assert entry.validation.get("reason"), f"{language} is report-only without a reason"


def test_tsx_and_javascript_follow_their_fallback_language(shipped):
    state_of = quality_wiring.calibration_state_lookup(shipped)
    for variant, base in LANGUAGE_FALLBACKS.items():
        assert state_of(variant) == state_of(base)
