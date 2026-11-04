"""Pure SVG helpers shared by the chart, diagram, flow and wireframe renderers.

Styling is by class only (colours come from `--vd-*` tokens in `static/css`):
no `style=` attribute, no fixed width, every text from props escaped.
"""

from varde_learn.docs.pages.blocks_render.common import esc, table

_MARKER_SHAPES = ("circle", "square", "triangle", "diamond", "cross", "plus")
_DASHES = ("", "6 3", "2 3", "8 3 2 3", "1 4", "10 4")


def svg_root(
    title: str,
    desc: str,
    viewbox: tuple[float, float, float, float],
    inner: str,
    cls: str = "",
) -> str:
    """An `<svg>` with role=img, `<title>`, `<desc>` and a viewBox, no fixed size."""
    box = " ".join(f"{v:g}" for v in viewbox)
    css = f' class="{esc(cls)}"' if cls else ""
    return (
        f'<svg{css} viewBox="{box}" role="img" aria-label="{esc(title)}">'
        f"<title>{esc(title)}</title><desc>{esc(desc)}</desc>{inner}</svg>"
    )


def marker_shape(index: int) -> str:
    """Series differentiator besides colour: a point-marker shape name."""
    return _MARKER_SHAPES[index % len(_MARKER_SHAPES)]


def dash(index: int) -> str:
    """Series differentiator besides colour: a `stroke-dasharray` ('' is solid)."""
    return _DASHES[index % len(_DASHES)]


def wrap_text(text: str, width: int) -> list[str]:
    """Break text into lines of at most `width` characters; long words are split."""
    width = max(width, 1)
    lines: list[str] = []
    current = ""
    for word in text.split():
        rest = word
        while len(rest) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(rest[:width])
            rest = rest[width:]
        joined = f"{current} {rest}" if current else rest
        if len(joined) <= width:
            current = joined
            continue
        lines.append(current)
        current = rest
    if current:
        lines.append(current)
    return lines


def data_table(
    headers: list[object],
    rows: list[list[object]],
    alt: str = "",
    summary: str = "Data table",
) -> str:
    """Text and table fallback for a drawing, collapsed in a `<details>`."""
    note = f'<p class="vb-alt">{esc(alt)}</p>' if alt else ""
    grid = table([esc(h) for h in headers], [[esc(c) for c in row] for row in rows])
    head = f"<summary>{esc(summary)}</summary>"
    return f'<details class="vb-data">{head}{note}{grid}</details>'


def copy_attr(text: str) -> str:
    """The `data-copy` attribute the action menu's Copy entry reads."""
    return f' data-copy="{esc(text)}"'
