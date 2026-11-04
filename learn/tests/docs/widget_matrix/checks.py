"""Pure matrix checks on plain snapshot data (no browser).

`audit.COLLECT_JS` gathers a snapshot dict in the page; every function here
takes that data and returns a list of problem strings, empty when it passes.
"""

from __future__ import annotations

from typing import Any

from .colors import backdrop, contrast_ratio, ratio_over

Snapshot = dict[str, Any]
Problems = list[str]

MIN_TARGET = 44
MIN_INLINE_TARGET = 24
TEXT_RATIO = 4.5
LARGE_TEXT_RATIO = 3.0
NON_TEXT_RATIO = 3.0
MAX_BROKEN_AVERAGE = 3.0  # characters per line at or below which a word is broken
OVERLAP_SLOP = 1.0  # px of shared edge that is not an overlap
CHART_FAMILIES = ("rich-chart", "rich-chart-events", "rich-tables")
VALID_ARIA = frozenset(
    [
        "activedescendant",
        "atomic",
        "autocomplete",
        "busy",
        "checked",
        "colcount",
        "colindex",
        "colspan",
        "controls",
        "current",
        "describedby",
        "description",
        "details",
        "disabled",
        "errormessage",
        "expanded",
        "flowto",
        "haspopup",
        "hidden",
        "invalid",
        "keyshortcuts",
        "label",
        "labelledby",
        "level",
        "live",
        "modal",
        "multiline",
        "multiselectable",
        "orientation",
        "owns",
        "placeholder",
        "posinset",
        "pressed",
        "readonly",
        "relevant",
        "required",
        "roledescription",
        "rowcount",
        "rowindex",
        "rowspan",
        "selected",
        "setsize",
        "sort",
        "valuemax",
        "valuemin",
        "valuenow",
        "valuetext",
    ]
)
VALID_ROLES = frozenset(
    [
        "alert",
        "alertdialog",
        "application",
        "article",
        "banner",
        "button",
        "cell",
        "checkbox",
        "columnheader",
        "combobox",
        "complementary",
        "contentinfo",
        "definition",
        "dialog",
        "directory",
        "document",
        "feed",
        "figure",
        "form",
        "grid",
        "gridcell",
        "group",
        "heading",
        "img",
        "link",
        "list",
        "listbox",
        "listitem",
        "log",
        "main",
        "marquee",
        "math",
        "menu",
        "menubar",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "navigation",
        "none",
        "note",
        "option",
        "presentation",
        "progressbar",
        "radio",
        "radiogroup",
        "region",
        "row",
        "rowgroup",
        "rowheader",
        "scrollbar",
        "search",
        "searchbox",
        "separator",
        "slider",
        "spinbutton",
        "status",
        "switch",
        "tab",
        "table",
        "tablist",
        "tabpanel",
        "term",
        "textbox",
        "timer",
        "toolbar",
        "tooltip",
        "tree",
        "treegrid",
        "treeitem",
    ]
)
NAME_REQUIRED = frozenset(
    [
        "button",
        "link",
        "checkbox",
        "radio",
        "textbox",
        "combobox",
        "slider",
        "spinbutton",
        "switch",
        "menuitem",
        "tab",
        "searchbox",
        "listbox",
    ]
)


def check_overflow(snap: Snapshot) -> Problems:
    doc = snap["doc"]
    problems: Problems = []
    if doc["scrollWidth"] > doc["clientWidth"]:
        problems.append(
            f"overflow: page scrolls horizontally ({doc['scrollWidth']} > "
            f"{doc['clientWidth']})"
        )
    problems += [
        f"overflow: {w['sel']} is {w['width']:.0f}px in a "
        f"{w['container']:.0f}px container"
        for w in snap["wide"]
    ]
    return problems


def target_minimum(control: Snapshot) -> int:
    return MIN_INLINE_TARGET if control["inline"] else MIN_TARGET


def _is_graph_node(sel: str) -> bool:
    """Graph nodes sit on a fitted pan/zoom canvas; zoom serves touch."""
    return "svg.vd-svg" in sel and ("g.vd-node" in sel or "g.vd-group-head" in sel)


def check_target_sizes(snap: Snapshot) -> Problems:
    problems: Problems = []
    for c in snap["controls"]:
        if _is_graph_node(c["sel"]):
            continue
        need, rect = target_minimum(c), c["target"]
        if rect["w"] < need or rect["h"] < need:
            problems.append(
                f"target-size: {c['sel']} is {rect['w']:.0f}x{rect['h']:.0f}, "
                f"needs {need}x{need}"
            )
    return problems


def _overlap(a: Snapshot, b: Snapshot) -> bool:
    width = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    height = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return width > OVERLAP_SLOP and height > OVERLAP_SLOP


def check_target_overlap(snap: Snapshot) -> Problems:
    # The audit already merges a control with its label, so targets are distinct.
    targets = snap["controls"]
    return [
        f"target-overlap: {a['sel']} overlaps {b['sel']}"
        for i, a in enumerate(targets)
        for b in targets[i + 1 :]
        if _overlap(a.get("reach", a["target"]), b.get("reach", b["target"]))
    ]


def check_no_char_wrap(snap: Snapshot) -> Problems:
    """A word broken into a few letters per line (`2/0/1`, `k/e/y`) is a defect."""
    return [
        f"char-wrap: {c['sel']} '{c['text']}' averages "
        f"{c['length'] / c['lines']:.1f} characters per line"
        for c in snap.get("charWrap", [])
        if c["length"] / c["lines"] <= MAX_BROKEN_AVERAGE
    ]


def check_no_split_dates(snap: Snapshot) -> Problems:
    """An ISO date broken across lines (`2026-/11-04`) is a defect."""
    return [
        f"split-date: {d['sel']} '{d['text']}' wraps across lines"
        for d in snap.get("splitDates", [])
    ]


def check_no_pin_overlap(snap: Snapshot) -> Problems:
    """A code pin drawn over the text of its own line is a defect."""
    return [
        f"pin-overlap: {p['sel']} covers '{p['text']}'"
        for p in snap.get("pinOverlap", [])
    ]


def check_text_contrast(snap: Snapshot, scheme: str) -> Problems:
    problems: Problems = []
    for t in snap["texts"]:
        if t["unverifiable"]:
            continue
        ratio = ratio_over(t["fg"], t["bgs"], scheme, t["opacity"])
        if ratio is None:
            continue
        need = LARGE_TEXT_RATIO if t["large"] else TEXT_RATIO
        if ratio < need:
            problems.append(
                f"text-contrast: {t['sel']} '{t['text']}' {ratio:.2f}:1, needs {need}:1"
            )
    return problems


def check_non_text_contrast(snap: Snapshot, scheme: str) -> Problems:
    problems: Problems = []
    for n in snap["nontext"]:
        if n["unverifiable"]:
            continue
        ratio = ratio_over(n["color"], n["bgs"], scheme)
        if ratio is not None and ratio < NON_TEXT_RATIO:
            problems.append(
                f"non-text-contrast: {n['kind']} of {n['sel']} {ratio:.2f}:1, "
                f"needs {NON_TEXT_RATIO}:1"
            )
    return problems


def selection_by_fill_only(selected: Snapshot) -> bool:
    return selected["borderWidth"] < 2 and not selected["glyph"]


def check_selection(snap: Snapshot) -> Problems:
    return [
        f"selection: {s['sel']} is marked by fill alone (needs a 2px border or glyph)"
        for s in snap["selected"]
        if selection_by_fill_only(s)
    ]


def check_forced_colors(snap: Snapshot) -> Problems:
    problems = check_selection(snap)
    problems += [
        f"forced-colors: {n['sel']} has no border ({n['kind']})"
        for n in snap["bordersLost"]
    ]
    return problems


def _ring_width(stop: Snapshot) -> float:
    outline = stop["outline"]
    if outline["style"] not in ("none", "hidden") and outline["width"] > 0:
        return outline["width"]
    return stop["shadowWidth"]


def check_focus(stops: list[Snapshot], scheme: str, forced: bool = False) -> Problems:
    problems: Problems = []
    for stop in stops:
        sel = stop["sel"]
        if _ring_width(stop) <= 0:
            problems.append(f"focus-visible: {sel} shows no ring")
            continue
        if stop["clipped"]:
            problems.append(f"focus-clipped: {sel} ring is cut by an ancestor overflow")
        if not stop["inView"]:
            problems.append(f"focus-scroll: {sel} was not scrolled into view")
        if stop["obscuredBy"]:
            problems.append(f"focus-obscured: {sel} sits under {stop['obscuredBy']}")
        if not forced:
            problems += _ring_contrast(stop, scheme)
    return problems


def _ring_contrast(stop: Snapshot, scheme: str) -> Problems:
    color = stop["ringColor"]
    problems: Problems = []
    for where, layers in (
        ("outside", stop["outsideBgs"]),
        ("inside", stop["insideBgs"]),
    ):
        ratio = ratio_over(color, layers, scheme)
        if ratio is not None and ratio < NON_TEXT_RATIO:
            problems.append(
                f"focus-contrast: {stop['sel']} ring {ratio:.2f}:1 against the "
                f"{where} neighbour, needs {NON_TEXT_RATIO}:1"
            )
    return problems


def check_names(snap: Snapshot) -> Problems:
    problems: Problems = []
    for c in snap["controls"]:
        if c["role"] in NAME_REQUIRED and not c["name"].strip():
            problems.append(f"name: {c['sel']} ({c['role']}) has no accessible name")
        if c["role"] == "radio" and not c["groupName"].strip():
            problems.append(f"radio-group: {c['sel']} is not in a named group")
    problems += [f"image-alt: {i} has no alt" for i in snap["imagesWithoutAlt"]]
    problems += [f"duplicate-id: '{i}' is used more than once" for i in snap["dupIds"]]
    problems += _aria_problems(snap["aria"])
    problems += [
        f"aria-ref: {r['sel']} {r['attr']} points at a missing id"
        for r in snap["badRefs"]
    ]
    if not snap["doc"]["lang"]:
        problems.append("lang: <html> has no lang attribute")
    if not snap["doc"]["title"].strip():
        problems.append("document-title: the page has no title")
    return problems


def _aria_problems(items: list[Snapshot]) -> Problems:
    problems: Problems = []
    for item in items:
        if item["attr"] == "role":
            valid = all(r in VALID_ROLES for r in item["value"].split())
            if not valid:
                problems.append(f"aria-role: {item['sel']} has role '{item['value']}'")
        elif item["attr"].removeprefix("aria-") not in VALID_ARIA:
            problems.append(f"aria-valid: {item['sel']} has unknown {item['attr']}")
    return problems


def check_print(snap: Snapshot) -> Problems:
    problems = [f"print-clipped: {c['sel']} cuts off content" for c in snap["clipped"]]
    problems += check_selection(snap)
    return problems


def _series_key(series: Snapshot) -> tuple[str, str, str]:
    return series["marker"], series["dash"], series["pattern"]


def check_series(series: list[Snapshot]) -> Problems:
    """Series must differ by a label, marker, dash or pattern, not colour alone."""
    keys = [_series_key(s) for s in series]
    problems: Problems = []
    for i, s in enumerate(series):
        has_label = bool(s["label"].strip())
        shares_key = keys.count(keys[i]) > 1 or not any(keys[i])
        if not has_label and shares_key:
            problems.append(f"series-colour-only: '{s['id']}' has no label or marker")
    return problems


def check_nojs_fallback(roots: list[Snapshot], family: str) -> Problems:
    problems: Problems = []
    for root in roots:
        if not root["hasAlt"]:
            problems.append(f"nojs-alt: {root['sel']} has no text alternative")
        if family in CHART_FAMILIES and not root["hasTable"]:
            problems.append(f"nojs-table: {root['sel']} has no data table fallback")
    return problems


def run_checks(
    snap: Snapshot, stops: list[Snapshot], *, scheme: str, mode: str, family: str
) -> Problems:
    """Every check that applies to one matrix mode."""
    rich = family.startswith("rich-")
    problems = check_overflow(snap)
    if mode == "print":
        series = check_series(snap["series"]) if rich else []
        return problems + check_print(snap) + series
    if mode == "forced-colors":
        return problems + check_forced_colors(snap) + check_names(snap)
    problems += check_target_sizes(snap) + check_target_overlap(snap)
    problems += check_no_char_wrap(snap) + check_no_split_dates(snap)
    problems += check_no_pin_overlap(snap)
    problems += check_text_contrast(snap, scheme) + check_non_text_contrast(
        snap, scheme
    )
    problems += check_selection(snap) + check_names(snap) + check_focus(stops, scheme)
    if rich:
        problems += check_series(snap["series"])
    if rich and mode == "nojs":
        problems += check_nojs_fallback(snap["richRoots"], family)
    return problems


__all__ = ["backdrop", "contrast_ratio", "run_checks"]
