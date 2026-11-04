"""Survey rendering: capped text (about 600 tokens) and the JSON `data` block."""

from __future__ import annotations

from dataclasses import asdict

from .survey import Survey

MAX_BYTES = 2400
LIST_CAP = 8


def survey_data(survey: Survey) -> dict[str, object]:
    return asdict(survey)


def _names(items: list[str]) -> str:
    shown = ", ".join(items[:LIST_CAP])
    extra = len(items) - LIST_CAP
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def _token_lines(survey: Survey) -> list[str]:
    sources = [f"{path} ({count})" for path, count in survey.token_sheets]
    sources += survey.token_json + survey.theme_configs
    if not sources:
        return ["tokens: no tokens found"]
    return [f"tokens: {survey.token_total} custom properties", _names(sources)]


def _component_lines(survey: Survey) -> list[str]:
    if not survey.components:
        return ["components: no component library"]
    return [
        f"components: {len(survey.components)} in {_names(survey.component_dirs)}",
        _names(survey.components),
    ]


def _page_lines(survey: Survey) -> list[str]:
    if not survey.pages:
        return ["pages: none found"]
    top = [f"{path} (score {score})" for path, score in survey.pages[:3]]
    return ["pages (best first):", *top]


def render_survey(survey: Survey) -> str:
    """Plain text report, cut to MAX_BYTES; absent dimensions are said, not hidden."""
    frameworks = ", ".join(survey.frameworks) or "none detected"
    lines = [
        f"framework: {frameworks}; styling: {survey.styling}",
        *_token_lines(survey),
        *_component_lines(survey),
        *_page_lines(survey),
        f"design docs: {_names(survey.docs)}" if survey.docs else "design docs: none",
    ]
    if survey.truncated:
        lines.append("truncated: walk stopped at its file or time cap")
    text = "\n".join(lines) + "\n"
    return text.encode()[:MAX_BYTES].decode(errors="ignore")
