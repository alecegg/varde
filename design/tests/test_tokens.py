from pathlib import Path

from varde_design import tokens as t

ROOT = ":root{--a:#fff;--b:var(--a);--c:var(--missing, 4px);--d:var(--e);--e:var(--d)}"


def style_of(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / "corpus" / "rules" / name
    text = path.read_text(encoding="utf-8")
    return text.split("<style>")[1].split("</style>")[0]


def test_extracts_custom_properties_with_lines() -> None:
    found = t.extract_tokens("a{x:1}\n:root{\n--a: #fff;\n--b: 4px}")
    assert {k: (v.value, v.line) for k, v in found.items()} == {
        "--a": ("#fff", 3),
        "--b": ("4px", 4),
    }


def test_ignores_custom_properties_outside_token_selectors() -> None:
    assert t.extract_tokens(".card{--local:1px}") == {}


def test_theme_and_html_selectors_declare_tokens() -> None:
    css = '[data-theme="dark"]{--bg:#000} html{--x:1px}'
    assert sorted(t.extract_tokens(css)) == ["--bg", "--x"]


def test_last_declaration_wins() -> None:
    assert t.extract_tokens(":root{--a:1px}:root{--a:2px}")["--a"].value == "2px"


def test_resolve_chain_fallback_and_cycle() -> None:
    values = t.resolved_values(t.extract_tokens(ROOT))
    assert values["--b"] == "#fff"
    assert values["--c"] == "4px"
    assert "var(" in values["--d"]


def test_resolve_stops_at_depth_five() -> None:
    chain = "".join(f"--v{i}:var(--v{i + 1});" for i in range(8)) + "--v8:7px;"
    tokens = t.extract_tokens(f":root{{{chain}}}")
    assert t.resolve("var(--v4)", tokens) == "7px"
    assert t.resolve("var(--v3)", tokens) == "var(--v8)"
    assert t.resolve("var(--v0)", tokens, depth=9) == "7px"


def test_resolve_unknown_without_fallback_is_kept() -> None:
    assert t.resolve("1px var(--none)", {}) == "1px var(--none)"


def test_usage_counts_from_fixture() -> None:
    css = style_of("S7/clean.html")
    counts = t.usage_counts(css, t.extract_tokens(css))
    assert counts["--accent"] == 4
    assert counts["--radius"] == 2
    assert counts["--muted"] == 0


def test_byte_cap_and_sheet_cap(monkeypatch) -> None:
    monkeypatch.setattr(t, "MAX_SHEET_BYTES", 10)
    assert t.extract_tokens(":root{--a:1px;--b:2px}") == {}
    monkeypatch.setattr(t, "MAX_SHEET_BYTES", 1000)
    monkeypatch.setattr(t, "MAX_SHEETS", 2)
    sheets = [":root{--a:1px}", ":root{--b:1px}", ":root{--c:1px}"]
    assert sorted(t.collect_tokens(sheets)) == ["--a", "--b"]


def test_entry_cap(monkeypatch) -> None:
    monkeypatch.setattr(t, "MAX_ENTRIES", 2)
    assert len(t.extract_tokens(":root{--a:1;--b:2;--c:3}")) == 2


def test_later_sheet_overrides() -> None:
    merged = t.collect_tokens([":root{--a:1px}", ":root{--a:2px}"])
    assert merged["--a"].value == "2px"
