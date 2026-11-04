"""Finalize the per-language validation state of ``cal-1.toml`` (t10).

    uv run python baseline_build_cal.py --finalize --cal cal-1.toml \
        --constraints constraints.json --q4q5 q4q5.json --agreement agreement.json \
        --verdict resolver/notes/dev-final/verdict.md

A language becomes ``baseline-validated`` only when it has at least
``MIN_AGREED`` agreed cells, passing hard constraints, Q4 and Q5, and a resolver
verdict file that says PASS. Otherwise it stays ``report-only`` and the reason
names every unmet condition. ``validated`` is true only when all three v1
languages are ``baseline-validated``. No parameter is changed to pass. No model
call.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LANGUAGES = ("python", "typescript", "csharp")
MIN_AGREED = 3
PENDING = "pending constraints"
VALIDATED = "baseline-validated"
REPORT_ONLY = "report-only"


def resolver_reason(verdict_text: str | None) -> str | None:
    if verdict_text is None:
        return "resolver verdict missing"
    if not re.search(r"\bPASS\b", verdict_text):
        return "resolver verdict not PASS"
    return None


def agreed_count(agreement: Mapping[str, Any], language: str) -> int:
    return sum(
        1
        for cell in agreement.values()
        if cell.get("language") == language and cell.get("agreed") is True
    )


def unmet_reasons(
    language: str,
    constraints: Mapping[str, Any],
    q4q5: Mapping[str, Any],
    agreement: Mapping[str, Any],
    verdict_text: str | None,
) -> list[str]:
    reasons = []
    resolver = resolver_reason(verdict_text)
    if resolver:
        reasons.append(resolver)
    agreed = agreed_count(agreement, language)
    if agreed < MIN_AGREED:
        reasons.append(f"agreement {agreed}/{MIN_AGREED} agreed cells")
    for name, status in constraints["verdict"][language].items():
        if str(status).lower() != "pass":
            reasons.append(f"constraints {name.replace('_', ' ')} {status}")
    for question in ("q4", "q5"):
        cell = q4q5[f"{language}:{question}"]
        if not cell["pass"]:
            reasons.append(f"{question.upper()} {cell['rate']} below threshold")
    return reasons


def decide_states(
    constraints: Mapping[str, Any],
    q4q5: Mapping[str, Any],
    agreement: Mapping[str, Any],
    verdict_text: str | None,
) -> dict[str, tuple[str, str]]:
    """Per language: (state, reason). Pure."""
    states = {}
    for language in LANGUAGES:
        reasons = unmet_reasons(language, constraints, q4q5, agreement, verdict_text)
        if reasons:
            states[language] = (REPORT_ONLY, "; ".join(reasons))
        else:
            states[language] = (VALIDATED, "all validation conditions hold")
    return states


def apply_states(text: str, states: Mapping[str, tuple[str, str]]) -> str:
    """cal-1 text with each language's state and reason set, ``validated`` derived."""
    for language, (state, reason) in states.items():
        header = f"[language.{language}.validation]\n"
        pattern = re.compile(re.escape(header) + r'state = "[^"]*"\nreason = "[^"]*"\n')
        replacement = f'{header}state = "{state}"\nreason = "{reason}"\n'
        text, count = pattern.subn(lambda _match, new=replacement: new, text)
        if count != 1:
            raise ValueError(f"validation table for {language} not found once")
    all_valid = all(state == VALIDATED for state, _ in states.values())
    return re.sub(
        r"^validated = (true|false)$",
        f"validated = {'true' if all_valid else 'false'}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def reset_states(text: str) -> str:
    """Undo finalization, so a rebuild can be compared with a finalized file."""
    pending = dict.fromkeys(LANGUAGES, (REPORT_ONLY, PENDING))
    return apply_states(text, pending)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finalize", action="store_true", required=True)
    parser.add_argument("--cal", type=Path, required=True)
    parser.add_argument("--constraints", type=Path, required=True)
    parser.add_argument("--q4q5", type=Path, required=True)
    parser.add_argument("--agreement", type=Path, required=True)
    parser.add_argument("--verdict", type=Path, required=True)
    args = parser.parse_args(argv)
    verdict = args.verdict.read_text() if args.verdict.is_file() else None
    states = decide_states(
        json.loads(args.constraints.read_text()),
        json.loads(args.q4q5.read_text()),
        json.loads(args.agreement.read_text()),
        verdict,
    )
    args.cal.write_text(apply_states(reset_states(args.cal.read_text()), states))
    for language, (state, reason) in states.items():
        print(f"{language}: {state} ({reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
