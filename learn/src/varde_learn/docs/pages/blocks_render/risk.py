"""HTML for the risks block: a 3x3 likelihood-by-impact grid and the full risk list.

Server-rendered; no script. Severity (likelihood x impact) is a glyph plus a word, and
the grid cell border style (solid, dashed, double) repeats it for grey print. The grid
is a summary (`role=img` with counts); the `<dl>` list carries every field.
"""

from varde_learn.docs.pages.blocks_render.common import as_list, count_noun, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

LEVELS = ("low", "medium", "high")
SCORE = {"low": 1, "medium": 2, "high": 3}
SEVERITIES = ("low", "medium", "high", "critical")
GLYPHS = {"low": "○", "medium": "◐", "high": "▲", "critical": "◆"}
WORDS = {"low": "Low", "medium": "Medium", "high": "High", "critical": "Critical"}
CHIPS_PER_CELL = 4
Risk = dict[str, object]


def severity_of(likelihood: str, impact: str) -> str:
    """Score likelihood x impact (1 to 9): 1-2 low, 3-4 medium, 6 high, 9 critical."""
    score = SCORE[likelihood] * SCORE[impact]
    if score <= 2:
        return "low"
    if score <= 4:
        return "medium"
    return "high" if score <= 6 else "critical"


def _severity(risk: Risk) -> str:
    return severity_of(str(risk["likelihood"]), str(risk["impact"]))


def summary_text(risks: list[Risk]) -> str:
    """`4 risks: 1 critical, 2 high, 1 low`; counts of zero are left out."""
    parts = [
        f"{n} {s}"
        for s in reversed(SEVERITIES)
        if (n := sum(1 for r in risks if _severity(r) == s))
    ]
    return f"{count_noun(len(risks), 'risk', 'risks')}: {', '.join(parts)}"


def copy_text(risks: list[Risk]) -> str:
    lines = []
    for r in risks:
        line = (
            f"{r['id']}: {r['label']} (likelihood {r['likelihood']}, "
            f"impact {r['impact']}, severity {_severity(r)})"
        )
        for key in ("mitigation", "owner"):
            line += f"; {key}: {r[key]}" if key in r else ""
        lines.append(line)
    return "\n".join(lines)


def _cell(likelihood: str, impact: str, risks: list[Risk]) -> str:
    sev = severity_of(likelihood, impact)
    here = [r for r in risks if r["likelihood"] == likelihood and r["impact"] == impact]
    chips = "".join(
        f'<span class="vd-risk-chip">{esc(r["id"])}</span>'
        for r in here[:CHIPS_PER_CELL]
    )
    extra = len(here) - CHIPS_PER_CELL
    more = f'<span class="vd-risk-more">+{extra}</span>' if extra > 0 else ""
    empty = "" if here else " vd-risk-empty"
    return (
        f'<div class="vd-risk-cell vd-risk-cell-{sev}{empty}">'
        f'<span class="vd-risk-glyph">{GLYPHS[sev]}</span>{chips}{more}</div>'
    )


def _grid(risks: list[Risk]) -> str:
    heads = "".join(f'<span class="vd-risk-colhead">{WORDS[i]}</span>' for i in LEVELS)
    rows = ""
    for likelihood in reversed(LEVELS):
        cells = "".join(_cell(likelihood, impact, risks) for impact in LEVELS)
        rows += f'<span class="vd-risk-rowhead">{WORDS[likelihood]}</span>{cells}'
    return (
        f'<div class="vd-risk-grid" role="img" aria-label="{esc(summary_text(risks))}">'
        f'<span class="vd-risk-corner"></span>{heads}{rows}</div>'
    )


def _field(key: str, value_html: str) -> str:
    return f'<dd><span class="vd-risk-key">{key}</span> {value_html}</dd>'


def _entry(risk: Risk) -> str:
    sev = _severity(risk)
    fields = (
        _field("Likelihood", esc(WORDS[str(risk["likelihood"])]))
        + _field("Impact", esc(WORDS[str(risk["impact"])]))
        + _field(
            "Severity",
            f'<span class="vd-risk-sevmark" aria-hidden="true">{GLYPHS[sev]}</span> '
            f'<span class="vd-risk-sevword">{WORDS[sev]}</span>',
        )
    )
    for key in ("mitigation", "owner"):
        if key in risk:
            fields += _field(key.capitalize(), esc(risk[key]))
    return (
        f'<div class="vd-risk-entry vd-risk-sev-{sev}">'
        f'<dt><span class="vd-risk-id">{esc(risk["id"])}</span> '
        f'<span class="vd-risk-label">{esc(risk["label"])}</span></dt>{fields}</div>'
    )


def render_risk(data: dict[str, object]) -> str:
    risks = [r for r in as_list(data["item"]) if isinstance(r, dict)]
    title = str(data.get("title") or "Risks")
    caption = (
        f'<p class="vd-risk-title">{esc(data["title"])}</p>'
        if data.get("title")
        else ""
    )
    axes = (
        '<p class="vd-risk-axes">Rows are likelihood, high at the top. '
        "Columns are impact, low at the left.</p>"
    )
    entries = "".join(_entry(r) for r in risks)
    return (
        f'<section class="vb risks vd-risk" aria-label="{esc(title)}"'
        f"{copy_attr(copy_text(risks))}>"
        f"{caption}"
        f'<p class="vb-alt vd-risk-summary">{esc(summary_text(risks))}</p>'
        f"{axes}{_grid(risks)}"
        f'<dl class="vd-risk-list">{entries}</dl></section>'
    )
