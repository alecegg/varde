"""The `recap` block: `varde learn docs recap --json` output shown as changes and drift.

Pure functions. Every value from the diff (file names, hunks, task ids) is escaped
text; the only attributes carrying data are `data-*` and in-page `id`/`href`
values built from escaped text or counters. Judgment buttons are wired by
`static/recap.js`.
"""

from varde_learn.docs.pages.blocks_render.common import (
    as_dict,
    as_list,
    card,
    esc,
    table,
)

VERDICTS = {"accepted": "Accept", "rejected": "Reject", "open": "Open"}
_REQUIRED_ROW_KEYS = ("file", "status", "hunk")


def _error(message: str) -> str:
    items = f"<ul><li>{esc(message)}</li></ul>"
    return (
        '<div class="vb">'
        + card("recap block has 1 error", items, "vb-error")
        + "</div>"
    )


def parse_recap(props: dict) -> tuple[dict | None, str]:
    """Return (recap props, "") or (None, reason)."""
    rows = props.get("rows")
    if not isinstance(rows, list):
        return None, "recap needs a `rows` list"
    for row in rows:
        if not isinstance(row, dict) or any(k not in row for k in _REQUIRED_ROW_KEYS):
            return None, "each recap row needs file, status and hunk"
    return props, ""


def drift_items(data: dict) -> list[tuple[str, str]]:
    """Return (item key, label) for each drift flag, in a stable order."""
    rows = as_list(data.get("rows"))
    items = [
        (f"unplanned:{r['file']}", f"unplanned change: {r['file']}")
        for r in rows
        if "unplanned" in as_list(r.get("drift"))
    ]
    for raw in as_list(data.get("untouched")):
        task, owns = as_dict(raw).get("task", ""), as_dict(raw).get("owns", "")
        items.append((f"untouched:{task}:{owns}", f"untouched: {task} owns {owns}"))
    items.extend(
        (f"unverified:{b}", f"unverified block: {b}")
        for b in as_list(data.get("unverified"))
    )
    return items


def _file_anchor(prefix: str, index: int) -> str:
    return f"{prefix}-f{index}"


def _mapping(data: dict, prefix: str) -> str:
    by_block: dict[str, list[str]] = {}
    for index, row in enumerate(as_list(data.get("rows"))):
        for block in as_list(row.get("blocks")):
            link = f'<a href="#{_file_anchor(prefix, index)}">{esc(row["file"])}</a>'
            by_block.setdefault(str(block), []).append(link)
    rows = [[esc(b), ", ".join(links)] for b, links in sorted(by_block.items())]
    rows += [
        [esc(b), "no changed file"]
        for b in as_list(data.get("unverified"))
        if str(b) not in by_block
    ]
    if not rows:
        return "<p>No plan block is linked to a change.</p>"
    return table(["Plan block", "Changed files"], rows)


def _buttons() -> str:
    return "".join(
        f'<button type="button" class="recap-verdict" data-verdict="{verdict}">'
        f"{label}</button>"
        for verdict, label in VERDICTS.items()
    )


def _drift(data: dict) -> str:
    items = drift_items(data)
    if not items:
        return "<p>No drift flagged.</p>"
    lines = "".join(
        f'<li class="recap-item" data-item="{esc(key)}">{esc(label)} '
        f'<span class="recap-buttons">{_buttons()}</span>'
        '<span class="recap-state" aria-live="polite"></span></li>'
        for key, label in items
    )
    return (
        f'<ul class="recap-drift">{lines}</ul><p class="recap-error" role="alert"></p>'
    )


def _ranges(prefix: str, index: int, row: dict) -> str:
    links = []
    for sign, key in (("+", "added"), ("-", "removed")):
        for pair in as_list(row.get(key)):
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            name = f"{_file_anchor(prefix, index)}-{key[0]}{pair[0]}-{pair[1]}"
            links.append(
                f'<a class="recap-range" id="{esc(name)}" href="#{esc(name)}">'
                f"{sign}{esc(pair[0])}-{esc(pair[1])}</a>"
            )
    return " ".join(links)


def _file(prefix: str, index: int, row: dict) -> str:
    tasks = ", ".join(str(t) for t in as_list(row.get("tasks"))) or (
        "shared" if row.get("shared") else "unplanned"
    )
    flags = " ".join(str(d) for d in as_list(row.get("drift")))
    head = f"{row['file']} ({row['status']}; {tasks}{'; ' + flags if flags else ''})"
    note = " (truncated)" if row.get("truncated") else ""
    hunk = "binary file" if row.get("binary") else str(row["hunk"])
    return (
        f'<details class="recap-file" id="{_file_anchor(prefix, index)}">'
        f"<summary>{esc(head)}{note}</summary>"
        f'<p class="recap-ranges">{_ranges(prefix, index, row)}</p>'
        f"<pre><code>{esc(hunk)}</code></pre></details>"
    )


def render_recap(props: dict, block_id: str | None) -> str:
    data, reason = parse_recap(props)
    if data is None:
        return _error(reason)
    prefix = f"recap-{block_id}" if block_id else "recap"
    summary = as_dict(data.get("summary"))
    counts = ", ".join(f"{esc(k)} {esc(v)}" for k, v in summary.items())
    files = "".join(_file(prefix, i, r) for i, r in enumerate(as_list(data["rows"])))
    span = f"{data.get('base', '')}..{data.get('head', '')}"
    heading = f"{esc(data.get('plan', ''))} {esc(span)}"
    inner = (
        f"<p>{counts}</p><h5>Plan blocks to changes</h5>{_mapping(data, prefix)}"
        f"<h5>Drift</h5>{_drift(data)}<h5>Files</h5>{files}"
    )
    return f'<div class="vb recap">{card(heading, inner)}</div>'
