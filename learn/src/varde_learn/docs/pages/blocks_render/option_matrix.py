"""HTML for the matrix block: an adapter that renders a typed table plus markers.

The props become table props (status columns for the options) and the landed table
renderer draws them. This module then marks the recommended column and swaps the
tone of high, medium and low ratings. Server-rendered; no script of its own.
"""

import re

from varde_learn.docs.pages.blocks.option_matrix import (
    FIRST_COLUMN,
    SCALES,
    rating_scale,
)
from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    count_noun,
    esc,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr
from varde_learn.docs.pages.blocks_render.tables import copy_text as table_copy
from varde_learn.docs.pages.blocks_render.tables import render_table

TOTAL_LABEL = "Weighted total"
NOT_RATED = "Not rated"
_LEVEL_TONES = {"high": ("ok", "✓"), "medium": ("warn", "▲"), "low": ("bad", "✕")}
_LEVEL_CELL = re.compile(
    r'<span class="vb-status vb-status-neutral">'
    r'<span class="vb-status-glyph" aria-hidden="true">●</span>'
    r"(high|medium|low)</span>",
    re.IGNORECASE,
)
_ROW = re.compile(r"<tr>.*?</tr>", re.DOTALL)
_CELL = re.compile(r'<(td|th)( scope="row")? data-label="([^"]*)"')
_HEAD_CELL = re.compile(r'<th scope="col">(.*?)</th>', re.DOTALL)


def scale_of(cells: list[list[object]]) -> str:
    found = (rating_scale(c) for row in cells for c in row)
    return next((s for s in found if s), "verdict")


def points(cell: object, scale: str) -> int:
    return SCALES[scale].get(str(cell).strip().lower(), 0)


def totals(
    cells: list[list[object]], weights: list[int], scale: str
) -> list[tuple[int, int]]:
    """(score, best possible) per option column."""
    best = 2 * sum(weights)
    return [
        (
            sum(
                w * points(row[i], scale) for row, w in zip(cells, weights, strict=True)
            ),
            best,
        )
        for i in range(len(cells[0]) if cells else 0)
    ]


def table_props(data: dict[str, object]) -> dict[str, object]:
    """The table block props the matrix is shown with."""
    options = [as_dict(o) for o in as_list(data["options"])]
    criteria = [as_dict(c) for c in as_list(data["criteria"])]
    cells = [as_list(r) for r in as_list(data["cells"])]
    weighted = any("weight" in c for c in criteria)
    weights = [int(c.get("weight", 1)) for c in criteria]
    rows: list[list[object]] = []
    for criterion, row in zip(criteria, cells, strict=True):
        label = str(criterion["label"])
        label += f" (weight {criterion['weight']})" if "weight" in criterion else ""
        rows.append([label, *(str(c).strip() or NOT_RATED for c in row)])
    if weighted:
        scored = totals(cells, weights, scale_of(cells))
        rows.append([TOTAL_LABEL, *(f"{got} of {best}" for got, best in scored)])
    labels = [str(o["label"]) for o in options]
    return {
        "caption": str(data.get("title", "Options compared")),
        "columns": [FIRST_COLUMN, *labels],
        "rows": rows,
        "types": dict.fromkeys(labels, "status"),
        "footnote": alternative(data, options, criteria, weighted),
        "stack": True,
    }


def alternative(
    data: dict[str, object],
    options: list[dict[str, object]],
    criteria: list[dict[str, object]],
    weighted: bool,
) -> str:
    """The text alternative: sizes, the recommendation and the scoring rule."""
    sizes = count_noun(len(options), "option", "options")
    sizes += f" compared on {count_noun(len(criteria), 'criterion', 'criteria')}."
    parts = [sizes]
    chosen = next((o for o in options if o["id"] == data.get("recommended")), None)
    if chosen:
        parts.append(f"Recommended: {chosen['label']}.")
    if weighted:
        parts.append(
            "Weighted total: yes or high scores 2, partial or medium 1, no or low 0, "
            "times the weight."
        )
    return " ".join(parts)


def copy_text(props: dict[str, object], recommended: str | None) -> str:
    """The matrix as a markdown table."""
    columns = [str(c) for c in as_list(props["columns"])]
    columns = [f"{c} (recommended)" if c == recommended else c for c in columns]
    rows = [as_list(r) for r in as_list(props["rows"])]
    lines = [columns, ["---"] * len(columns), *rows]
    return "\n".join(
        "| "
        + " | ".join(" ".join(str(c).split()).replace("|", "\\|") for c in line)
        + " |"
        for line in lines
    )


def _rec_head(inner: str, label: str) -> str:
    # The "Recommended" badge is drawn by CSS (::after), outside the sort button.
    return (
        f'<th scope="col" class="vd-matrix-rec" aria-label="{label}, Recommended">'
        f"{inner}</th>"
    )


def mark_head(html: str, index: int, label: str) -> str:
    count = -1

    def swap(found: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return _rec_head(found[1], label) if count == index else found[0]

    head, sep, rest = html.partition("</thead>")
    return _HEAD_CELL.sub(swap, head) + sep + rest


def mark_cells(html: str, index: int, label: str) -> str:
    """Tag the recommended column's body cells and name them for the stacked view."""

    def row(found: re.Match[str]) -> str:
        count = -1

        def cell(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if count != index:
                return match[0]
            tag = f"<{match[1]}{match[2] or ''}"
            return f'{tag} class="vd-matrix-rec" data-label="{label} (recommended)"'

        return _CELL.sub(cell, found[0])

    head, sep, rest = html.partition("</thead>")
    return head + sep + _ROW.sub(row, rest)


def tone_levels(html: str) -> str:
    def swap(found: re.Match[str]) -> str:
        kind, glyph = _LEVEL_TONES[found[1].lower()]
        return (
            f'<span class="vb-status vb-status-{kind}">'
            f'<span class="vb-status-glyph" aria-hidden="true">{glyph}</span>'
            f"{found[1]}</span>"
        )

    return _LEVEL_CELL.sub(swap, html)


def _notes(options: list[dict[str, object]]) -> str:
    items = "".join(
        f"<li><strong>{esc(o['label'])}</strong>: {esc(o['note'])}</li>"
        for o in options
        if "note" in o
    )
    if not items:
        return ""
    return (
        '<div class="vd-matrix-notes" role="region" tabindex="0" '
        f'aria-label="Option notes"><ul>{items}</ul></div>'
    )


def render_matrix(data: dict[str, object]) -> str:
    props = table_props(data)
    options = [as_dict(o) for o in as_list(data["options"])]
    cells = [as_list(r) for r in as_list(data["cells"])]
    columns = as_list(props["columns"])
    rows = [as_list(r) for r in as_list(props["rows"])]
    old = f'<div class="vb table"{copy_attr(table_copy(columns, rows, []))}>'
    html = render_table(props)
    chosen = next((o for o in options if o["id"] == data.get("recommended")), None)
    label = esc(chosen["label"]) if chosen else None
    if chosen:
        index = options.index(chosen) + 1
        html = mark_cells(mark_head(html, index, label or ""), index, label or "")
    if scale_of(cells) == "level":
        html = tone_levels(html)
    copy = copy_text(props, str(chosen["label"]) if chosen else None)
    new = f'<div class="vb matrix vd-matrix"{copy_attr(copy)}>'
    return html.replace(old, new, 1).removesuffix("</div>") + _notes(options) + "</div>"
