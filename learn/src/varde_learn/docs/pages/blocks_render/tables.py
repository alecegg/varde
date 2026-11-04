"""HTML for the table block: a scroll region around a typed, groupable table."""

from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    card,
    dated_html,
    esc,
)
from varde_learn.docs.pages.blocks_render.svg import copy_attr

_GOOD = ("ok", "pass", "passed", "done", "success", "healthy", "yes", "complete")
_WARN = ("warn", "warning", "partial", "pending", "slow", "degraded", "at risk")
_BAD = ("fail", "failed", "error", "blocked", "no", "down", "broken")
_BAR_WIDTH = 100
_BAR_HEIGHT = 8


def status_kind(text: str) -> tuple[str, str]:
    """(css modifier, glyph) for a status word; the word itself always shows."""
    word = text.strip().lower()
    if word in _GOOD:
        return "ok", "✓"
    if word in _WARN:
        return "warn", "▲"
    if word in _BAD:
        return "bad", "✕"
    return "neutral", "●"


def link_parts(cell: object) -> tuple[str, str]:
    """(label, url) of a link cell: a URL string or a [label, url] pair."""
    if isinstance(cell, list) and len(cell) == 2:
        return str(cell[0]), str(cell[1])
    return str(cell), str(cell)


def bar_percent(value: float, top: float) -> float:
    if top <= 0:
        return 0.0
    return max(0.0, min(100.0, value / top * 100))


def plain_text(cell: object) -> str:
    """One cell as copyable text: no tabs or line breaks."""
    label, url = link_parts(cell) if isinstance(cell, list) else (str(cell), "")
    text = f"{label} ({url})" if url and url != label else label
    return " ".join(text.split())


def copy_text(
    columns: list[object], rows: list[list[object]], groups: list[str]
) -> str:
    """Tab-separated header and rows; a leading `group` column when grouped."""
    header = [plain_text(c) for c in columns]
    lines = ["\t".join((["group"] if groups else []) + header)]
    for row, group in zip(rows, groups or [""] * len(rows), strict=True):
        cells = [plain_text(c) for c in row]
        lines.append("\t".join(([plain_text(group)] if groups else []) + cells))
    return "\n".join(lines)


def group_labels(data: dict[str, object], row_count: int) -> list[str]:
    """One group label per row, empty when the table has no groups."""
    labels: list[str] = []
    for group in as_list(data.get("groups")):
        labels += [str(as_dict(group).get("label", ""))] * int(
            as_dict(group).get("rows", 0)
        )
    return labels if len(labels) == row_count else []


def _link_html(cell: object) -> str:
    from varde_learn.docs.pages.render import classify_url  # render imports blocks

    label, url = link_parts(cell)
    kind = classify_url(url)
    if kind == "link":
        return f'<a href="{esc(url)}" rel="noopener noreferrer">{esc(label)}</a>'
    if kind == "relative":
        return f'<span class="relative-link" title="{esc(url)}">{esc(label)}</span>'
    return esc(label)


def _bar_html(cell: object, top: float) -> str:
    value = float(str(cell))
    width = bar_percent(value, top) * _BAR_WIDTH / 100
    box = f"0 0 {_BAR_WIDTH} {_BAR_HEIGHT}"
    bar = (
        f'<svg class="vb-bar-svg" viewBox="{box}" aria-hidden="true" focusable="false">'
        f'<rect class="vb-bar-track" width="{_BAR_WIDTH}" height="{_BAR_HEIGHT}"/>'
        f'<rect class="vb-bar-fill" width="{width:.1f}" height="{_BAR_HEIGHT}"/></svg>'
    )
    return f'{bar}<span class="vb-bar-num">{esc(cell)}</span>'


def _status_html(cell: object) -> str:
    kind, glyph = status_kind(str(cell))
    mark = f'<span class="vb-status-glyph" aria-hidden="true">{glyph}</span>'
    return f'<span class="vb-status vb-status-{kind}">{mark}{esc(cell)}</span>'


def cell_html(cell: object, kind: str, top: float) -> str:
    if kind == "link":
        return _link_html(cell)
    if kind == "bar":
        return _bar_html(cell, top)
    if kind == "status":
        return _status_html(cell)
    return dated_html(cell)


def _num_class(kind: str) -> str:
    return ' class="vb-num"' if kind in ("number", "bar") else ""


def _row(
    row: list[object],
    columns: list[object],
    kinds: list[str],
    tops: list[float],
    row_header: bool,
) -> str:
    cells = []
    for index, cell in enumerate(row):
        tag = "th" if row_header and index == 0 else "td"
        scope = ' scope="row"' if tag == "th" else ""
        label = esc(columns[index])
        inner = cell_html(cell, kinds[index], tops[index])
        cells.append(
            f'<{tag}{scope}{_num_class(kinds[index])} data-label="{label}">'
            f"{inner}</{tag}>"
        )
    return "<tr>" + "".join(cells) + "</tr>"


def _head(columns: list[object], kinds: list[str]) -> str:
    cells = "".join(
        f'<th scope="col"{_num_class(k)}>{esc(c)}</th>'
        for c, k in zip(columns, kinds, strict=True)
    )
    return f"<thead><tr>{cells}</tr></thead>"


def _bodies(
    rows: list[list[object]],
    labels: list[str],
    columns: list[object],
    kinds: list[str],
    tops: list[float],
    row_header: bool,
) -> str:
    out: list[str] = []
    previous: str | None = None
    for row, label in zip(rows, labels or [""] * len(rows), strict=True):
        if label != previous or not out:
            if out:
                out.append("</tbody>")
            out.append("<tbody>")
            if labels:
                span = len(columns)
                out.append(
                    f'<tr class="vb-group-head"><th scope="colgroup" colspan="{span}">'
                    f"{esc(label)}</th></tr>"
                )
            previous = label
        out.append(_row(row, columns, kinds, tops, row_header))
    return "".join(out) + "</tbody>"


def _column_tops(rows: list[list[object]], kinds: list[str]) -> list[float]:
    """Largest value of each bar column (0 for other columns): the bar scale."""
    return [
        max((float(str(r[i])) for r in rows), default=0.0) if kind == "bar" else 0.0
        for i, kind in enumerate(kinds)
    ]


def render_table(data: dict[str, object]) -> str:
    columns = as_list(data["columns"])
    rows = [as_list(r) for r in as_list(data["rows"])]
    types = as_dict(data.get("types"))
    kinds = [str(types.get(str(c), "text")) for c in columns]
    labels = group_labels(data, len(rows))
    stack = data.get("stack") is True
    sticky = data.get("sticky_column") is True
    classes = "vb-table" + (" vb-table-stack" if stack else "")
    classes += " vb-table-sticky" if sticky else ""
    name = str(data.get("caption", "Table"))
    size = f"{len(rows)} rows, {len(columns)} columns"
    note = esc(data["footnote"]) if "footnote" in data else esc(size)
    grid = (
        f'<table class="{classes}" aria-label="{esc(name)} ({esc(size)})">'
        f"{_head(columns, kinds)}"
        f"{_bodies(rows, labels, columns, kinds, _column_tops(rows, kinds), sticky)}"
        "</table>"
    )
    region = (
        f'<div class="vb-scroll" role="region" tabindex="0" aria-label="{esc(name)}">'
        f"{grid}</div>"
    )
    foot = f'<p class="vb-alt vb-foot">{note}</p>'
    heading = esc(data["caption"]) if "caption" in data else ""
    copy = copy_attr(copy_text(columns, rows, labels))
    return f'<div class="vb table"{copy}>{card(heading, region + foot)}</div>'
