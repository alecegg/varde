"""Component `image`: a captioned picture from a file beside the document.

Pure checks only; the page assembler reads the file (`pages.media`). `src` is a
relative path with an allowed extension. URLs, absolute paths and `..` are refused
here, and symlinks that leave the document's directory are refused when the file
is opened.
"""

import re
from posixpath import splitext

from varde_learn.docs.pages.blocks.image_header import EXTENSIONS
from varde_learn.docs.pages.blocks.rules import Fault, check_keys, str_field
from varde_learn.docs.pages.blocks.spec import BlockSpec

WIDTHS = ("narrow", "full")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:|^//")


def src_fault(src: str) -> str | None:
    """Why `src` cannot name a file beside the document, or None."""
    if not src.strip() or "\x00" in src or "\\" in src:
        return "image src must be a relative path"
    if _SCHEME.match(src):
        return f"image src '{src}' must be a file path, not a URL"
    if src.startswith("/"):
        return f"image src '{src}' must be relative, not absolute"
    parts = [part for part in src.split("/") if part not in {"", "."}]
    if ".." in parts:
        return f"image src '{src}' must not use '..'"
    if any(part.startswith(".") for part in parts):
        return f"image src '{src}' names a dotfile or dot-directory"
    if splitext(src.lower())[1] not in EXTENSIONS:
        allowed = ", ".join(sorted(EXTENSIONS))
        return f"image src '{src}' must end in one of {allowed}"
    return None


def validate_image(data: dict[str, object]) -> list[Fault]:
    faults = check_keys(data, {"src", "alt"}, {"caption", "width"}, "image")
    for key in ("src", "alt", "caption"):
        faults += str_field(data, key, "image")
    src = data.get("src")
    if isinstance(src, str) and src.strip() and (reason := src_fault(src)):
        faults.append(Fault("src", reason))
    if "width" in data and data["width"] not in WIDTHS:
        faults.append(Fault("type", f"image: width must be one of {', '.join(WIDTHS)}"))
    return faults


IMAGE = BlockSpec(
    "image",
    "A captioned picture from a png, jpeg, webp, gif or svg file beside the page",
    (
        "src      relative path from the page's directory; png, jpg, jpeg, webp,",
        "         gif or svg; no URLs, absolute paths, '..' or dotfiles; at most 5 MB",
        "alt      what the picture shows (required; decorative images are not offered)",
        "caption  optional text under the picture",
        "width    optional: narrow (about 24rem) or full (default, column width)",
        "  The file is shown as an <img> only (an svg is never inlined) and is",
        "  served from the page's own directory. A page export embeds a file up",
        "  to 1 MB and otherwise shows the alt text and caption with a note.",
    ),
    r"""image = image(
  src: "img/login-screen.png",
  alt: "The login screen with the email field focused",
  caption: "Login after the redesign",
  width: "narrow",
)
""",
    validate_image,
)
