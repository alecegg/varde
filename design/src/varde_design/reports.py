"""Report builders for `tokens` and `survey`. Pure."""

from __future__ import annotations

from typing import Any

from .check import style_sheets
from .report import build_report, checked_block
from .survey import build_survey
from .survey_report import render_survey, survey_data
from .tokens import Token, extract_tokens, resolve

NO_TOKENS = "tokens: no tokens found"


def tokens_report(
    files: dict[str, str],
    extra_sheets: list[str] | None = None,
    *,
    settings_source: str = "defaults",
    skipped: list[str] | None = None,
) -> dict[str, Any]:
    """Custom-property map the checker would use; later sheets win."""
    merged: dict[str, tuple[str, Token]] = {}
    sources = [("", sheet) for sheet in extra_sheets or []]
    for file, text in files.items():
        sources += [(file, sheet) for sheet in style_sheets(file, text)]
    for file, sheet in sources:
        for name, token in extract_tokens(sheet).items():
            merged[name] = (file, token)
    everything = {name: token for name, (_, token) in merged.items()}
    rows = [
        {
            "name": name,
            "value": token.value,
            "resolved": resolve(token.value, everything),
            "file": file,
            "line": token.line,
            "selector": token.selector,
        }
        for name, (file, token) in sorted(merged.items())
    ]
    not_run = list(skipped or [])
    if not rows:
        not_run.append(NO_TOKENS)
    checked = checked_block(
        tiers=["static"], widths=[], settings_source=settings_source,
        elements=len(rows), not_run=not_run,
    )  # fmt: skip
    return build_report("tokens", [], checked, {"tokens": rows})


def survey_report(
    paths: list[str],
    texts: dict[str, str],
    *,
    truncated: bool = False,
    skipped: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Survey report dict and its capped plain-text rendering."""
    survey = build_survey(paths, texts, truncated)
    not_run = list(skipped or [])
    if truncated:
        not_run.append("walk stopped at its file or time cap")
    checked = checked_block(
        tiers=["survey"], widths=[], settings_source="defaults",
        elements=len(paths), not_run=not_run,
    )  # fmt: skip
    report = build_report("survey", [], checked, survey_data(survey))
    return report, render_survey(survey)
