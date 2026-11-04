"""HTML for the image block: a `<figure>` with a lazy `<img>`, caption and description.

Server-rendered. Width and height come from the file header so the layout never
shifts. Without script the picture links to the file; `image.js` adds a zoom dialog.
The `vb-alt` line repeats the alt text as plain text for readers without the picture.
"""

from urllib.parse import quote

from varde_learn.docs.pages.blocks_render.common import card, esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr
from varde_learn.docs.pages.media import Media

NOT_EMBEDDED = "Image not embedded in this export."
OPEN_LABEL = "Open image full size"
UNRESOLVED = "Image not shown: this page cannot read the file here."


def copy_text(data: dict[str, object]) -> str:
    return "\n".join(str(data[key]) for key in ("alt", "caption") if key in data)


def media_url(src: str) -> str:
    return "/media/" + quote(src)


def _width_class(data: dict[str, object]) -> str:
    return "vd-image-narrow" if data.get("width") == "narrow" else "vd-image-full"


def _picture(data: dict[str, object], media: Media, *, export: bool) -> str:
    source = media.data_url if export else media_url(media.src)
    img = (
        f'<img class="vd-image-img" src="{esc(source)}" alt="{esc(data["alt"])}" '
        f'width="{media.width}" height="{media.height}" '
        'loading="lazy" decoding="async">'
    )
    if export:
        return img
    label = (
        f"{data['alt']} (open full size)" if str(data["alt"]).strip() else OPEN_LABEL
    )
    return (
        f'<a class="vd-image-link" href="{esc(media_url(media.src))}" '
        f'aria-label="{esc(label)}">{img}</a>'
    )


def _missing(note: str) -> str:
    mark = '<span aria-hidden="true">&#9888; </span>'
    return f'<p class="vd-image-missing">{mark}{esc(note)}</p>'


def _figure(data: dict[str, object], inner: str, summary: str) -> str:
    caption = (
        f'<figcaption class="vd-image-caption">{esc(data["caption"])}</figcaption>'
        if data.get("caption")
        else ""
    )
    return (
        f'<figure class="vb image vd-image {_width_class(data)}"'
        f"{copy_attr(copy_text(data))}>{inner}{caption}"
        f'<p class="vb-alt vd-image-alt">{esc(summary)}</p></figure>'
    )


def render_image(data: dict[str, object], media: Media, *, export: bool = False) -> str:
    """The figure for a checked image file; `export` inlines it or falls back."""
    summary = f"Image: {data['alt']} ({media.width} x {media.height} px)"
    if export and not media.data_url:
        return _figure(data, _missing(NOT_EMBEDDED), summary)
    return _figure(data, _picture(data, media, export=export), summary)


def render_unresolved(data: dict[str, object]) -> str:
    """The figure where no file is available (an image inside an included part)."""
    return _figure(data, _missing(UNRESOLVED), f"Image: {data['alt']}")


def render_refused(props: dict[str, object], reasons: list[str]) -> str:
    """The error card for an image that cannot be shown, with a text alternative."""
    items = "".join(f"<li>{esc(reason)}</li>" for reason in reasons)
    alt = str(props.get("alt") or "").strip() or "no description given"
    count = f"image block has {len(reasons)} error{'s' * (len(reasons) != 1)}"
    return (
        '<div class="vb">'
        + card(esc(count), f"<ul>{items}</ul>", "vb-error")
        + f'<p class="vb-alt">Image unavailable: {esc(alt)}</p></div>'
    )
