"""Per-language gating versus report-only for quality findings.

Pure functions. The caller supplies ``state_of(language)`` returning the
language's validation state (calibration t2's per-language accessor, or a stub);
only the calibration's gating states (``panel-validated`` and
``baseline-validated``) gate. Any other state, an unknown language or a
missing state caps the finding at ``info`` and labels it ``not validated``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from varde_code.quality_score.calibration.loading import GATING_STATES

NOT_VALIDATED_LABEL = "not validated"
CAPPED_SEVERITY = "info"

StateLookup = Callable[[str], str | None]


@dataclass(frozen=True)
class EffectiveMode:
    severity: str
    label: str | None
    gating: bool


def language_is_validated(state_of: StateLookup, language: str | None) -> bool:
    if not language:
        return False
    return state_of(language) in GATING_STATES


def effective_mode(
    severity: str, language: str | None, state_of: StateLookup
) -> EffectiveMode:
    """Keep severity for a validated language; else cap at info and label it."""
    if language_is_validated(state_of, language):
        return EffectiveMode(severity, None, severity == "error")
    return EffectiveMode(CAPPED_SEVERITY, NOT_VALIDATED_LABEL, False)


def gate_fails(findings: list[tuple[str, str | None]], state_of: StateLookup) -> bool:
    """True when any (severity, language) finding is a validated-language error."""
    return any(effective_mode(sev, lang, state_of).gating for sev, lang in findings)
