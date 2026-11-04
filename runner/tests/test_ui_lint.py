from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "ui" / "src"
NAMED_COLORS = {
    "aliceblue",
    "antiquewhite",
    "aqua",
    "aquamarine",
    "azure",
    "beige",
    "bisque",
    "black",
    "blanchedalmond",
    "blue",
    "blueviolet",
    "brown",
    "burlywood",
    "cadetblue",
    "chartreuse",
    "chocolate",
    "coral",
    "cornflowerblue",
    "cornsilk",
    "crimson",
    "cyan",
    "darkblue",
    "darkcyan",
    "darkgoldenrod",
    "darkgray",
    "darkgreen",
    "darkgrey",
    "darkkhaki",
    "darkmagenta",
    "darkolivegreen",
    "darkorange",
    "darkorchid",
    "darkred",
    "darksalmon",
    "darkseagreen",
    "darkslateblue",
    "darkslategray",
    "darkslategrey",
    "darkturquoise",
    "darkviolet",
    "deeppink",
    "deepskyblue",
    "dimgray",
    "dimgrey",
    "dodgerblue",
    "firebrick",
    "floralwhite",
    "forestgreen",
    "fuchsia",
    "gainsboro",
    "ghostwhite",
    "gold",
    "goldenrod",
    "gray",
    "green",
    "greenyellow",
    "grey",
    "honeydew",
    "hotpink",
    "indianred",
    "indigo",
    "ivory",
    "khaki",
    "lavender",
    "lavenderblush",
    "lawngreen",
    "lemonchiffon",
    "lightblue",
    "lightcoral",
    "lightcyan",
    "lightgoldenrodyellow",
    "lightgray",
    "lightgreen",
    "lightgrey",
    "lightpink",
    "lightsalmon",
    "lightseagreen",
    "lightskyblue",
    "lightslategray",
    "lightslategrey",
    "lightsteelblue",
    "lightyellow",
    "lime",
    "limegreen",
    "linen",
    "magenta",
    "maroon",
    "mediumaquamarine",
    "mediumblue",
    "mediumorchid",
    "mediumpurple",
    "mediumseagreen",
    "mediumslateblue",
    "mediumspringgreen",
    "mediumturquoise",
    "mediumvioletred",
    "midnightblue",
    "mintcream",
    "mistyrose",
    "moccasin",
    "navajowhite",
    "navy",
    "oldlace",
    "olive",
    "olivedrab",
    "orange",
    "orangered",
    "orchid",
    "palegoldenrod",
    "palegreen",
    "paleturquoise",
    "palevioletred",
    "papayawhip",
    "peachpuff",
    "peru",
    "pink",
    "plum",
    "powderblue",
    "purple",
    "rebeccapurple",
    "red",
    "rosybrown",
    "royalblue",
    "saddlebrown",
    "salmon",
    "sandybrown",
    "seagreen",
    "seashell",
    "sienna",
    "silver",
    "skyblue",
    "slateblue",
    "slategray",
    "slategrey",
    "snow",
    "springgreen",
    "steelblue",
    "tan",
    "teal",
    "thistle",
    "tomato",
    "turquoise",
    "violet",
    "wheat",
    "white",
    "whitesmoke",
    "yellow",
    "yellowgreen",
}
RAW_VALUE = re.compile(
    r"#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color-mix)\s*\(",
    re.IGNORECASE,
)
DECLARATION = re.compile(r"([\w-]+)\s*:\s*([^;{}]+)")
FORBIDDEN_PROPERTIES = {
    "font",
    "font-size",
    "height",
    "min-height",
    "max-height",
    "block-size",
    "min-block-size",
    "max-block-size",
    "inline-size",
    "min-inline-size",
    "max-inline-size",
}


def violations(text: str) -> bool:
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.DOTALL))
    for iter_prop, iter_value in DECLARATION.findall(css):
        prop, value = iter_prop.lower(), iter_value.strip()
        if prop.startswith("--"):
            continue
        if prop == "font":
            return True
        if prop in FORBIDDEN_PROPERTIES and re.search(
            r"\b\d+(?:\.\d+)?(?:px|rem|em|vh|vw|dvh|dvw|%)\b", value, re.IGNORECASE
        ):
            return True
        if RAW_VALUE.search(value) or re.search(
            r"\b(?:" + "|".join(NAMED_COLORS) + r")\b", value, re.IGNORECASE
        ):
            return True
    for attr in re.findall(r'\bstyle\s*=\s*["\']([^"\']*)', text, re.IGNORECASE):
        if violations(f"<style>.x{{{attr}}}</style>"):
            return True
    return bool(
        re.search(
            r'\bclass\s*=\s*["\'][^"\']*\[[^\]]*(?:#[\da-f]|\d+(?:px|rem|vh)|(?:red|blue|green|black|white))',
            text,
            re.IGNORECASE,
        )
    )


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("<style>.x{color:var(--text-body);height:var(--control-h)}</style>", False),
        ("<style>.x{color:inherit;background:transparent}</style>", False),
        ("<style>.x{background:red}</style>", True),
        ("<style>.x{color:oklch(1 0 0)}</style>", True),
        ("<style>.x{min-height:2rem}</style>", True),
        ("<style>.x{border:1px solid #fff}</style>", True),
        ("<style>.x{border-top:1px solid red}</style>", True),
        ("<style>.x{box-shadow:0 0 0 2px rgb(0 0 0)}</style>", True),
        ("<style>.x{fill:#000}</style>", True),
        ("<style>.x{color:crimson}</style>", True),
        ("<style>.x{block-size:44px}</style>", True),
        ("<style>.x{font:600 13px/1 sans-serif}</style>", True),
        ('<div style="color: red">', True),
        ('<div class="h-[42px]">', True),
    ],
)
def test_lint_rule_examples(snippet: str, expected: bool) -> None:
    assert violations(snippet) is expected


def test_route_and_non_ui_component_styles_use_shared_tokens() -> None:
    offenders: dict[str, list[int]] = {}
    paths = [*ROOT.glob("routes/**/*.svelte"), *ROOT.glob("lib/**/*.svelte")]
    for path in paths:
        if path.is_relative_to(ROOT / "lib" / "ui"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.DOTALL):
            for line, content in enumerate(
                match.group(1).splitlines(), text.count("\n", 0, match.start(1)) + 1
            ):
                if violations(f"<style>{content}</style>"):
                    offenders.setdefault(path.relative_to(ROOT).as_posix(), []).append(
                        line
                    )
    allowlist = ROOT.parents[1] / "tests" / "ui_lint_allowlist.txt"
    allowed = {}
    if allowlist.exists():
        for line in allowlist.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry, separator, reason = line.partition("#")
                assert separator and reason.strip(), (
                    f"allowlist entry needs a reason: {line}"
                )
                name, count = entry.strip().rsplit(":", 1)
                allowed[name] = int(count)
    actual = {name: len(lines) for name, lines in offenders.items()}
    assert actual == allowed, (
        f"UI style violations path:count changed: actual={actual}; "
        f"allowlisted={allowed}; lines={offenders}"
    )


def test_viewport_meta_allows_mobile_zoom_and_safe_area() -> None:
    html = (ROOT / "app.html").read_text(encoding="utf-8")
    match = re.search(r'<meta\s+name="viewport"\s+content="([^"]+)"', html)
    assert match, "app.html is missing viewport meta"
    content = dict(
        (key.strip(), value.strip()) if "=" in part else (part.strip(), "")
        for part in match.group(1).split(",")
        for key, value in [part.split("=", 1) if "=" in part else (part, "")]
    )
    assert content.get("width") == "device-width"
    assert content.get("initial-scale") == "1"
    assert content.get("viewport-fit") == "cover"
    assert content.get("interactive-widget") == "resizes-content"
    assert "maximum-scale" not in content and content.get(
        "user-scalable", ""
    ).lower() not in {"0", "no"}


def test_app_header_is_shell_owned_and_has_no_route_geometry_overrides() -> None:
    shell = (ROOT / "lib/chat/ChatShell.svelte").read_text(encoding="utf-8")
    chat_header = (ROOT / "lib/ChatHeader.svelte").read_text(encoding="utf-8")
    assert shell.count("<AppHeader ") == 1
    assert ":global(.chat-shell > .app-header)" in shell
    assert "width:min(calc(100% - 320px),1120px)" in shell
    assert "margin:0 0 16px calc(320px + max(0px,(100% - 320px - 1120px)/2))" in shell
    assert "<AppHeader" not in chat_header

    app_header_files = [
        ROOT / "lib/chat/AppHeader.svelte",
        ROOT / "lib/chat/ChatShell.svelte",
    ]
    for path in [*ROOT.glob("routes/**/*.svelte"), *ROOT.glob("lib/**/*.svelte")]:
        if path in app_header_files:
            continue
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\.app-header\s*\{", source), (
            f"{path.relative_to(ROOT)} overrides shared header geometry"
        )


def copy_violations(text: str) -> list[str]:
    errors = []
    for line in text.splitlines():
        raw_enum = r"<Badge[^>]*>\s*\{\s*\w+\.(?:state|status|outcome)\s*\}\s*</Badge>"
        if re.search(raw_enum, line) or re.search(
            r"<Badge[^>]*>\s*(?:running|succeeded|success|paused|queued|failed|blocked|pending|open|done|in_progress|needs_review|builder|planner|reviewer|guard|plan)\s*</Badge>",
            line,
        ):
            errors.append("raw enum badge")
        if len(re.findall(r"Not reported", line, re.IGNORECASE)) > 1:
            errors.append("duplicate Not reported")
        if re.search(r"(?:/private/var/|/Users/|/home/)[^\s<\"']+", line):
            errors.append("raw filesystem path")
        if re.search(r">[^<]*\bSDK\b[^<]*<", line):
            errors.append("unexplained SDK copy")
    return errors


def test_routes_use_shared_copy_rules() -> None:
    offenders = {}
    for path in [*ROOT.glob("routes/**/*.svelte"), *ROOT.glob("lib/**/*.svelte")]:
        if path.is_relative_to(ROOT / "routes" / "_catalog"):
            continue
        if path.is_relative_to(ROOT / "lib" / "ui"):
            continue
        errors = copy_violations(path.read_text(encoding="utf-8"))
        if errors:
            offenders[path.relative_to(ROOT).as_posix()] = errors
    assert not offenders, offenders


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("<Badge>{job.state}</Badge>", ["raw enum badge"]),
        ("<Badge>{instance.state}</Badge>", ["raw enum badge"]),
        ("<Badge>{label}</Badge>", []),
        (
            "<span>Not reported</span> · <span>Not reported</span>",
            ["duplicate Not reported"],
        ),
        ("<span>/private/var/tmp/seed</span>", ["raw filesystem path"]),
        ("<button>Preview SDK changes</button>", ["unexplained SDK copy"]),
        ("<button>Preview Claude Code changes</button>", []),
    ],
)
def test_copy_lint_examples(snippet: str, expected: list[str]) -> None:
    assert copy_violations(snippet) == expected
