"""Static `check` orchestration. Pure: file texts and settings in, report dict out."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from .css_rules import check_css
from .css_scanner import scan_css
from .html_rules import check_html
from .html_scanner import parse_html
from .ignores import Ignore, apply_ignores, parse_ignores
from .merge import RenderOutcome, merge_findings
from .motion_rules import check_reduced_motion
from .report import Finding, build_report, checked_block
from .settings import Settings
from .token_rules import check_token_rules
from .tokens import Token, collect_tokens

MAX_FINDINGS = 40
HTML_EXTS = (".html", ".htm")
CSS_EXTS = (".css",)
RENDER_NOT_RUN = "render: rendered tier not available (rules R1-R6, R8 and rendered R7)"


def is_html(file: str) -> bool:
    return file.lower().endswith(HTML_EXTS)


def is_css(file: str) -> bool:
    return file.lower().endswith(CSS_EXTS)


def style_sheets(file: str, text: str) -> list[str]:
    """CSS text a file contributes to the token set."""
    if is_css(file):
        return [text]
    if is_html(file):
        return [src.css for src in parse_html(text).styles]
    return []


def discover_tokens(files: dict[str, str], extra_sheets: list[str]) -> dict[str, Token]:
    sheets = list(extra_sheets)
    for file, text in files.items():
        sheets += style_sheets(file, text)
    return collect_tokens(sheets)


def _css_findings(
    text: str, file: str, settings: Settings, tokens: dict[str, Token]
) -> tuple[list[Finding], list[str]]:
    found = check_css(text, file, settings)
    result = check_token_rules(text, file, settings, tokens)
    found += result.findings
    if "S10" not in settings.ignore:
        pairs = [(rule, 0) for rule in scan_css(text)]
        found += check_reduced_motion(pairs, [text], file)
    return found, result.not_run


def _html_token_findings(
    text: str, file: str, settings: Settings, tokens: dict[str, Token]
) -> tuple[list[Finding], list[str]]:
    doc = parse_html(text)
    found: list[Finding] = []
    not_run: list[str] = []
    for src in doc.styles:
        result = check_token_rules(src.css, file, settings, tokens)
        owner = doc.elements[src.owner or 0]
        block = owner.tag == "style"
        for item in result.findings:
            selector = item.selector if block else f"{owner.tag}[style]"
            line = (item.line or 1) + src.line - 1
            found.append(replace(item, line=line, selector=selector))
        not_run += result.not_run
    return found, not_run


def _file_findings(
    file: str, text: str, settings: Settings, tokens: dict[str, Token]
) -> tuple[list[Finding], list[str]]:
    if is_css(file):
        return _css_findings(text, file, settings, tokens)
    found = check_html(text, file, settings)
    extra, not_run = _html_token_findings(text, file, settings, tokens)
    return found + extra, not_run


def _count_elements(file: str, text: str) -> int:
    if is_css(file):
        return len(scan_css(text))
    return len(parse_html(text).elements)


def _sort_key(finding: Finding) -> tuple[int, str, int, str]:
    return (
        0 if finding.severity == "fail" else 1,
        finding.file,
        finding.line or 0,
        finding.id,
    )


def cap_findings(
    findings: list[Finding],
) -> tuple[list[Finding], tuple[int, int] | None]:
    """Worst first, cut to MAX_FINDINGS; also (shown, total) when cut."""
    ordered = sorted(findings, key=_sort_key)
    if len(ordered) <= MAX_FINDINGS:
        return ordered, None
    return ordered[:MAX_FINDINGS], (MAX_FINDINGS, len(ordered))


def _collect_ignores(
    files: dict[str, str],
) -> tuple[list[Ignore], list[Finding]]:
    ignores: list[Ignore] = []
    bad: list[Finding] = []
    for file, text in files.items():
        found, malformed = parse_ignores(text, file)
        ignores += found
        bad += malformed
    return ignores, bad


def check_texts(  # noqa: PLR0913
    files: dict[str, str],
    settings: Settings,
    *,
    extra_sheets: list[str] | None = None,
    settings_source: str = "defaults",
    skipped: list[str] | None = None,
    static_only: bool = False,
    render: RenderOutcome | None = None,
) -> dict[str, Any]:
    """Report for check: every .html/.css text, ignores applied, capped.

    skipped holds the reasons files were not read (missing, oversized) and
    becomes not_run entries; extra_sheets are CSS texts used only for tokens.
    render is the rendered tier's outcome; without it (and without static_only)
    the tier is listed as not run.
    """
    tokens = discover_tokens(files, extra_sheets or [])
    found: list[Finding] = []
    not_run = list(skipped or [])
    for file, text in files.items():
        file_found, file_not_run = _file_findings(file, text, settings, tokens)
        found += file_found
        not_run += file_not_run
    ignores, malformed = _collect_ignores(files)
    rendered = render.findings if render else []
    merged = merge_findings(found, rendered) + malformed
    kept, echoes = apply_ignores(merged, ignores, settings.ignore)
    shown, truncated = cap_findings(kept)
    if not files:
        not_run.append("no .html or .css files to check")
    if render:
        not_run += render.not_run
    elif not static_only:
        not_run.append(RENDER_NOT_RUN)
    ran = bool(render and render.ran)
    elements = sum(_count_elements(f, t) for f, t in files.items())
    checked = checked_block(
        tiers=["static", "rendered"] if ran else ["static"],
        widths=render.widths if render else [],
        rendered=ran,
        notes=render.notes if render else [],
        settings_source=settings_source,
        elements=elements,
        truncated=truncated,
        not_run=_unique(not_run),
    )
    data = {"ignores": [asdict(echo) for echo in echoes], "files": sorted(files)}
    return build_report("check", shown, checked, data)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
