"""First-party HTML for the components; invalid blocks render an error card."""

from varde_learn.docs.pages.blocks import SPECS, check_props
from varde_learn.docs.pages.blocks_render.common import card, esc
from varde_learn.docs.pages.blocks_render.registry import COMPONENTS, Component


def error_card(title: str, lines: list[str]) -> str:
    items = "".join(f"<li>{esc(line)}</li>" for line in lines)
    return (
        '<div class="vb">'
        + card(esc(title), f"<ul>{items}</ul>", "vb-error")
        + "</div>"
    )


def errors_card(name: str, lines: list[str]) -> str:
    """`error_card` titled "<name> block has N error(s)"."""
    return error_card(
        f"{name} block has {len(lines)} error{'s' * (len(lines) != 1)}", lines
    )


def render_block(
    component: str, props: dict[str, object], block_id: str | None, line: int
) -> str:
    """HTML for one statement's props; `line` is its document line, for errors."""
    errors = [e.text() for e in check_props(component, props, line)]
    if errors:
        return errors_card(component, errors)
    data = {key: value for key, value in props.items() if key != "covers"}
    return COMPONENTS[component].render(data, block_id)


__all__ = [
    "COMPONENTS",
    "SPECS",
    "Component",
    "error_card",
    "errors_card",
    "render_block",
]
