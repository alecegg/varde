"""Props to the `recap` and `deps` renderers (they take the parsed props)."""

from varde_learn.docs.pages.blocks_render.common import as_dict
from varde_learn.docs.pages.graph import render_deps
from varde_learn.docs.pages.recap_block import render_recap


def render_recap_props(data: dict[str, object], block_id: str | None) -> str:
    return render_recap(data, block_id)


def render_deps_props(data: dict[str, object], block_id: str | None) -> str:
    return render_deps(as_dict(data.get("edges")))
