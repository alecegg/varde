"""The shared change vocabulary as HTML: a glyph, the word, the previous value.

Pure functions. The tone reaches the page only as a `vd-change-<change>` class, so
every colour comes from the `--vd-tone-*` tokens. Status is never colour alone: the
glyph and the word are text, and a removed row is struck through but stays readable.
"""

from collections.abc import Mapping, Sequence

from varde_learn.docs.pages.blocks_render.common import esc

FLAGS_HEAD = '<span class="vb-sr">flags</span>'
GLYPHS = {"added": "+", "modified": "~", "removed": "-", "renamed": "->"}


def change_of(item: Mapping[str, object]) -> tuple[str, str]:
    """The `(change, was)` pair of a validated table; empty strings when absent."""
    return str(item.get("change", "")), str(item.get("was", ""))


def change_badge(change: str, was: str = "") -> str:
    """Glyph plus word, plus the previous value; a rename shows it in the name."""
    glyph = (
        f'<span class="vd-change-glyph" aria-hidden="true">{esc(GLYPHS[change])}</span>'
    )
    badge = f'<span class="vd-change-badge vd-change-{change}">{glyph} {change}</span>'
    if not was or change == "renamed":
        return badge
    return f'{badge} <span class="vd-change-was">was {esc(was)}</span>'


def change_name(name_html: str, change: str, was: str, wrap: str = "span") -> str:
    """A name with the change styling; a rename reads `old -> new`."""
    if not change:
        return name_html
    name = f'<{wrap} class="vd-change-name">{name_html}</{wrap}>'
    if change != "renamed":
        return name
    old = f'<{wrap} class="vd-change-old">{esc(was)}</{wrap}>'
    return f"{old} &rarr; {name}"


def copy_line(change: str, name: str, was: str) -> str:
    """`<change> <name> (was <was>)` for the Copy entry of the action menu."""
    return f"{change} {name} (was {was})" if was else f"{change} {name}"


def legend(changes: Sequence[str]) -> str:
    """The text alternative: how many rows carry each change."""
    counts = [f"{changes.count(c)} {c}" for c in GLYPHS if c in changes]
    return f'<p class="vb-alt vd-change-legend">Changes: {", ".join(counts)}</p>'


def change_table(
    header: list[str], rows: list[tuple[list[str], str, str, str]], label: str
) -> str:
    """Rows are `(cells, change, was, label)`; cells are already escaped.

    With any change a `change` column holds the badge and each changed row carries
    its change class and an accessible name. The table is `vb-fields`, not
    `vb-table` (table.js would add sort buttons), inside a scroll region named
    `label`: a narrow card scrolls sideways instead of breaking words.
    """
    changed = any(change for _, change, _, _ in rows)
    head = "".join(f"<th>{c}</th>" for c in [*header, *(["change"] if changed else [])])
    body = "".join(_row(*row, changed=changed) for row in rows)
    return (
        f'<div class="vb-fields-scroll" role="region" aria-label="{esc(label)}" '
        f'tabindex="0"><table class="vb-fields"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _row(cells: list[str], change: str, was: str, label: str, *, changed: bool) -> str:
    badge = change_badge(change, was) if change else ""
    tds = "".join(f"<td>{c}</td>" for c in [*cells, *([badge] if changed else [])])
    if not change:
        return f"<tr>{tds}</tr>"
    name = esc(f"{change} {label}")
    return (
        f'<tr class="vd-change-row vd-change-{change}" aria-label="{name}">{tds}</tr>'
    )
