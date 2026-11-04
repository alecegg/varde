"""The image component: source rules, file checks, header sizes, export embedding."""

from __future__ import annotations

import base64
import os
import re
import struct
import zlib
from pathlib import Path

import pytest
from varde_learn.docs.pages import media
from varde_learn.docs.pages.assemble import assemble_page, assemble_static
from varde_learn.docs.pages.blocks import check, check_props
from varde_learn.docs.pages.blocks.image import src_fault
from varde_learn.docs.pages.blocks.image_header import read_header
from varde_learn.docs.pages.blocks_render.image import copy_text, render_unresolved
from varde_learn.docs.pages.media import Media, Problem, probe

FIXTURES = Path(__file__).parent / "fixtures" / "widgets"
TOKEN = "t"  # noqa: S105
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = (b"\x00" + b"\x10\x20\x30" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _page(tmp_path: Path, props: str = 'src: "a.png", alt: "A swatch"') -> Path:
    doc = tmp_path / "doc.md"
    body = props.replace(", ", ",\n  ")
    doc.write_text(f"# T\n\n```ui\nk = image(\n  {body},\n)\n```\n", encoding="utf-8")
    return doc


def _has_card(html: str, text: str) -> bool:
    return "vb-error" in html and text in html


@pytest.mark.parametrize(
    ("src", "text"),
    [
        ("../x.png", "'..'"),
        ("a/../../x.png", "'..'"),
        ("/etc/x.png", "absolute"),
        ("https://e.com/x.png", "URL"),
        ("HTTP://e.com/x.png", "URL"),
        ("data:image/png;base64,AAAA", "URL"),
        ("//e.com/x.png", "URL"),
        ("a\\b.png", "relative path"),
        (".hidden/x.png", "dotfile"),
        ("x.bmp", "must end in"),
        ("x", "must end in"),
        ("", "relative path"),
    ],
)
def test_source_rules_refuse_unsafe_paths(src: str, text: str) -> None:
    fault = src_fault(src)
    assert fault is not None
    assert text in fault


@pytest.mark.parametrize(
    "src", ["a.png", "img/a.JPG", "d/e f.webp", "x.gif", "./y.svg"]
)
def test_source_rules_accept_relative_files(src: str) -> None:
    assert src_fault(src) is None


def test_missing_alt_and_bad_props_are_faults() -> None:
    plain: dict[str, object] = {"src": "a.png", "alt": "x"}
    assert check_props("image", plain, 1) == []
    ok: dict[str, object] = {
        "src": "a.png",
        "alt": "x",
        "caption": "c",
        "width": "full",
    }
    assert check_props("image", ok, 1) == []
    bads: tuple[dict[str, object], ...] = (
        {"src": "a.png"},
        {"src": "a.png", "alt": ""},
        {"src": "a.png", "alt": "  "},
        {"alt": "x"},
        {"src": "a.png", "alt": "x", "width": "huge"},
        {"src": "a.png", "alt": "x", "caption": ""},
        {"src": "a.png", "alt": "x", "extra": 1},
        {"src": "../a.png", "alt": "x"},
    )
    for bad in bads:
        assert check_props("image", bad, 1), bad


def test_check_flags_a_statement_without_alt() -> None:
    text = '```ui\nk = image(\n  src: "a.png",\n)\n```\n'
    assert any("alt" in e.text() for e in check(text))


def test_figure_has_dimensions_lazy_loading_caption_and_alt(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(_png(40, 30))
    doc = _page(tmp_path, 'src: "a.png", alt: "A swatch", caption: "Cap"')
    html = assemble_page(doc, token=TOKEN)
    assert '<figure class="vb image vd-image vd-image-full"' in html
    assert 'width="40" height="30" loading="lazy" decoding="async"' in html
    assert 'alt="A swatch"' in html
    assert 'aria-label="A swatch (open full size)"' in html
    assert '<figcaption class="vd-image-caption">Cap</figcaption>' in html
    assert 'href="/media/a.png"' in html and 'src="/media/a.png"' in html
    assert '<p class="vb-alt vd-image-alt">Image: A swatch (40 x 30 px)</p>' in html
    assert 'data-copy="A swatch&#10;Cap"' in html or 'data-copy="A swatch\nCap"' in html
    assert copy_text({"alt": "A", "caption": "B"}) == "A\nB"


def test_width_narrow_class(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(_png(4, 4))
    doc = _page(tmp_path, 'src: "a.png", alt: "x", width: "narrow"')
    assert "vd-image-narrow" in assemble_page(doc, token=TOKEN)


def test_alt_and_caption_are_escaped(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(_png(4, 4))
    props = (
        'src: "a.png", alt: "<b>x</b> \\"q\\"", caption: "<script>alert(1)</script>"'
    )
    html = assemble_page(_page(tmp_path, props), token=TOKEN)
    assert "<script>alert" not in html and "<b>x</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt; &quot;q&quot;" in html


def test_missing_file_is_an_error_card(tmp_path: Path) -> None:
    html = assemble_page(_page(tmp_path), token=TOKEN)
    assert '<p class="vb-alt">Image unavailable: A swatch</p>' in html
    assert _has_card(html, "image &#x27;a.png&#x27; not found") or _has_card(
        html, "not found"
    )


def test_symlink_out_of_the_directory_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(_png(4, 4))
    site = tmp_path / "site"
    site.mkdir()
    os.symlink(outside / "secret.png", site / "a.png")
    doc = _page(site)
    html = assemble_page(doc, token=TOKEN)
    assert _has_card(html, "outside the page")
    assert isinstance(probe("a.png", site), Problem)


def test_symlink_inside_the_directory_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "real.png").write_bytes(_png(4, 4))
    os.symlink(tmp_path / "real.png", tmp_path / "a.png")
    assert isinstance(probe("a.png", tmp_path), Media)


def test_wrong_magic_bytes_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_text("<html>not a png</html>")
    html = assemble_page(_page(tmp_path), token=TOKEN)
    assert _has_card(html, "not a valid png file")
    (tmp_path / "b.png").write_bytes(GIF)  # a real gif named .png
    assert isinstance(probe("b.png", tmp_path), Problem)


def test_oversize_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.png").write_bytes(_png(40, 30))
    monkeypatch.setattr(media, "MAX_BYTES", 100)
    result = probe("a.png", tmp_path)
    assert isinstance(result, Problem) and "cap" in result.reason
    assert _has_card(assemble_page(_page(tmp_path), token=TOKEN), "cap")


def test_scheme_and_traversal_in_a_page_never_reach_the_disk(tmp_path: Path) -> None:
    (tmp_path.parent / "out.png").write_bytes(_png(4, 4))
    for src in ("../out.png", "https://e.com/a.png", "/etc/hosts.png"):
        html = assemble_page(_page(tmp_path, f'src: "{src}", alt: "x"'), token=TOKEN)
        assert "vb-error" in html and "<img" not in html


def test_svg_is_an_img_never_inline(tmp_path: Path) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20">'
        '<script>alert(1)</script><rect width="30" height="20"/></svg>'
    )
    (tmp_path / "a.svg").write_text(svg)
    doc = _page(tmp_path, 'src: "a.svg", alt: "Logo"')
    html = assemble_page(doc, token=TOKEN)
    assert 'src="/media/a.svg"' in html and "<img" in html
    assert "alert(1)" not in html and "<svg" not in html and "<object" not in html
    exported = assemble_static(doc).split("<main")[1]
    assert "data:image/svg+xml;base64," in exported
    assert "<svg" not in exported and "alert(1)" not in exported


def test_export_embeds_under_the_cap_and_falls_back_over_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _png(40, 30)
    (tmp_path / "a.png").write_bytes(data)
    doc = _page(tmp_path, 'src: "a.png", alt: "A swatch", caption: "Cap"')
    small = assemble_static(doc)
    encoded = base64.b64encode(data).decode()
    assert f'src="data:image/png;base64,{encoded}"' in small
    assert "/media/" not in small and "<a " not in small.split("<main")[1]
    monkeypatch.setattr(media, "EMBED_BYTES", 10)
    big = assemble_static(doc).split("<main")[1]
    assert "<img" not in big and "data:image" not in big
    assert "Image not embedded in this export." in big
    assert "A swatch" in big and "Cap" in big
    assert "/media/" in assemble_page(doc, token=TOKEN)  # the served page still links


def test_image_inside_an_included_part_shows_the_unresolved_figure() -> None:
    html = render_unresolved({"alt": "x<y", "caption": "c"})
    assert "x&lt;y" in html and "cannot read the file" in html and "<img" not in html


@pytest.mark.parametrize(
    ("name", "kind", "size"),
    [("shot.png", "png", (640, 360)), ("mark.svg", "svg", (200, 100)),
     ("dot.gif", "gif", (1, 1))],
)  # fmt: skip
def test_header_sizes_from_fixture_files(
    name: str, kind: str, size: tuple[int, int]
) -> None:
    data = (FIXTURES / "img" / name).read_bytes()
    assert read_header(data, kind) == size


def test_header_readers_for_jpeg_and_webp_and_svg_viewbox() -> None:
    jpeg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x0b\x08\x00\x20\x00\x30\x01\x01\x11\x00"
    )
    assert read_header(jpeg, "jpeg") == (48, 32)
    lossy = b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00" + b"\x00" * 6
    lossy += struct.pack("<HH", 50, 60)
    assert read_header(lossy, "webp") == (50, 60)
    wide = b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x0a\x00\x00\x00" + b"\x00" * 4
    wide += (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
    assert read_header(wide, "webp") == (100, 50)
    box = b'<svg viewBox="0 0 12.4 7"></svg>'
    assert read_header(box, "svg") == (12, 7)
    assert read_header(b"<svg></svg>", "svg") is None
    assert read_header(b"plain text", "png") is None
    assert (
        read_header(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 0, 5), "png"
        )
        is None
    )


def test_fixtures_render_without_error_cards_except_the_refused_ones() -> None:
    doc = FIXTURES / "rich-image.md"
    html = assemble_page(doc, token=TOKEN)
    assert "vb-error" not in html
    assert len(re.findall(r"<figure ", html)) == 4
    stress = assemble_page(FIXTURES / "rich-image-stress.md", token=TOKEN)
    assert stress.count("<figure ") == 204
    assert stress.count("vb-error") == 3
    assert "onerror=alert" not in stress.replace("&lt;img src=x onerror=alert", "")
