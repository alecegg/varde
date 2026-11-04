from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path


def _png_pixel(path: Path, x: int, y: int) -> tuple[int, int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    compressed = bytearray()
    width = height = bit_depth = color_type = 0
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break
        offset += 12 + length

    assert bit_depth == 8 and color_type in (2, 6)
    assert 0 <= x < width and 0 <= y < height
    bytes_per_pixel = 4 if color_type == 6 else 3
    row_bytes = width * bytes_per_pixel
    decoded = zlib.decompress(compressed)
    previous = bytearray(row_bytes)
    target = None
    cursor = 0
    for row_index in range(y + 1):
        filter_type = decoded[cursor]
        filtered = decoded[cursor + 1 : cursor + 1 + row_bytes]
        cursor += row_bytes + 1
        row = bytearray(row_bytes)
        for index, value in enumerate(filtered):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = (
                previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            )
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                p = left + above - upper_left
                distances = (abs(p - left), abs(p - above), abs(p - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                raise AssertionError(f"unsupported PNG filter {filter_type}")
            row[index] = (value + predictor) & 0xFF
        previous = row
        if row_index == y:
            pixel_offset = x * bytes_per_pixel
            target = (row[pixel_offset], row[pixel_offset + 1], row[pixel_offset + 2])
    assert target is not None
    return target


def _assert_close(actual: tuple[int, int, int], expected: str, tolerance: int) -> None:
    expected_rgb = tuple(int(expected[index : index + 2], 16) for index in (1, 3, 5))
    assert all(
        abs(value - target) <= tolerance
        for value, target in zip(actual, expected_rgb, strict=True)
    )


def test_legacy_app_icon_is_ignored(tmp_path):
    from varde_runner.web.settings import read_settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"app_icon": "26a", "other": "kept on disk"}))
    assert read_settings(path) == {"app_icon": "slate-bronze"}


def test_static_icon_sets_have_light_default_and_dark_variant():
    static = Path(__file__).parents[1] / "ui" / "static"
    assert all(
        (static / name).is_file()
        for name in (
            "favicon.svg",
            "favicon-16.png",
            "favicon-32.png",
            "apple-touch-icon.png",
            "icon-192.png",
            "icon-512.png",
            "manifest.webmanifest",
        )
    )
    assert all(
        (static / "icons" / "dark" / name).is_file()
        for name in (
            "favicon-16.png",
            "favicon-32.png",
            "apple-touch-icon.png",
            "icon-192.png",
            "icon-512.png",
        )
    )
    assert not any((static / "icons" / icon).exists() for icon in ("26a", "26b", "26c"))


def test_shipped_icon_samples_match_approved_appearances():
    static = Path(__file__).parents[1] / "ui" / "static"
    points = ((256, 200), (256, 290), (256, 380))
    expected = {
        "light": ("#D7B479", "#9CB6A8", "#ECE9DC"),
        "dark": ("#BB9B60", "#9CB6A8", "#E7E4D9"),
    }
    paths = {
        "light": static / "icon-512.png",
        "dark": static / "icons" / "dark" / "icon-512.png",
    }
    for appearance, path in paths.items():
        for point, color in zip(points, expected[appearance], strict=True):
            _assert_close(_png_pixel(path, *point), color, tolerance=10)
