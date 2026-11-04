"""Host-owned HTML shell shared by the served page and the static export."""

from __future__ import annotations

import html
import re
from functools import cache
from importlib.resources import files

# Load order for the known scripts (`recap.js` hosts `window.varde` and
# `inputs_ordered.js` uses it, so they come last in that order); any other
# `static/*.js` follows alphabetically.
_SCRIPT_ORDER = (
    "app.js",
    "blocks.js",
    "recap.js",
    "inputs_ordered.js",
)
_INPUT_TAGS = tuple(
    (f"<{tag} ", f"<{tag} disabled ")
    for tag in ("button", "textarea", "input", "select")
)


_MODULE_SYNTAX = re.compile(r"^(import|export)\s", re.MULTILINE)


@cache
def _is_es_module(name: str) -> bool:
    """A `static/*.js` with `import` or `export` lines is loaded by another script."""
    path = files("varde_learn.docs.pages").joinpath("static", name)
    return _MODULE_SYNTAX.search(path.read_text(encoding="utf-8")) is not None


def static_scripts() -> tuple[str, ...]:
    """Script file names shipped in `static/`, in page load order."""
    found = sorted(
        entry.name
        for entry in files("varde_learn.docs.pages").joinpath("static").iterdir()
        if entry.name.endswith(".js")
    )
    known = [name for name in _SCRIPT_ORDER if name in found]
    return (*known, *(name for name in found if name not in known))


def page_scripts() -> tuple[str, ...]:
    """`static_scripts` that get a script tag: ES modules are imported, not tagged."""
    return tuple(name for name in static_scripts() if not _is_es_module(name))


def static_css() -> str:
    """Page stylesheet: `static/css/*.css` concatenated in name order."""
    parts = sorted(
        (
            entry
            for entry in files("varde_learn.docs.pages")
            .joinpath("static", "css")
            .iterdir()
            if entry.name.endswith(".css")
        ),
        key=lambda entry: entry.name,
    )
    return "\n".join(entry.read_text(encoding="utf-8") for entry in parts)


def make_read_only(body: str) -> str:
    """Disable input widgets. Agent text is escaped, so these tags are host-made."""
    for tag, disabled in _INPUT_TAGS:
        body = body.replace(tag, disabled)
    return body


def _served_head(token: str, title_tag: str) -> str:
    scripts = "".join(
        f'<script src="/static/{n}" defer></script>' for n in page_scripts()
    )
    return (
        f'<meta name="varde-token" content="{html.escape(token)}">'
        f'{title_tag}<link rel="stylesheet" href="/static/app.css">{scripts}'
    )


def page_shell(title: str, main: str, token: str | None) -> str:
    """Served page when `token` is set; else self-contained with no script."""
    title_tag = f"<title>{html.escape(title)}</title>"
    if token is None:
        head = title_tag + f"<style>{static_css()}</style>"
    else:
        head = _served_head(token, title_tag)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{head}</head><body>{main}</body></html>"
    )
