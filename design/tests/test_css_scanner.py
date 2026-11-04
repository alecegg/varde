from varde_design.css_scanner import blank_comments, scan_css


def test_scanner_reports_selector_declarations_and_lines() -> None:
    rules = scan_css("a {\n  color: red;\n  margin: 0 }\n\n.b,\n.c { top: 1px; }")
    assert [r.selector for r in rules] == ["a", ".b,\n.c"]
    assert [(d.prop, d.value, d.line) for d in rules[0].declarations] == [
        ("color", "red", 2),
        ("margin", "0", 3),
    ]
    assert rules[1].line == 5
    assert rules[1].declarations[0].line == 6


def test_scanner_blanks_comments_but_keeps_line_numbers() -> None:
    text = "/* a { color: red } \n multi */\np { color: blue; /* x: y; */ }"
    assert blank_comments(text).count("\n") == text.count("\n")
    rules = scan_css(text)
    assert [r.selector for r in rules] == ["p"]
    assert rules[0].line == 3
    assert [d.prop for d in rules[0].declarations] == ["color"]


def test_scanner_keeps_semicolons_and_braces_inside_strings_and_urls() -> None:
    css = 'a { content: "a;b{c}"; background: url(data:image/png;base64,AA); top: 0 }'
    (rule,) = scan_css(css)
    assert [d.prop for d in rule.declarations] == ["content", "background", "top"]
    assert rule.declarations[1].value == "url(data:image/png;base64,AA)"


def test_scanner_tracks_wrapping_at_rules_as_context() -> None:
    css = "@media (min-width: 600px) {\n  .a { top: 0 }\n}\n.b { top: 1px }"
    rules = scan_css(css)
    assert [(r.selector, r.context, r.line) for r in rules] == [
        (".a", ("@media (min-width: 600px)",), 2),
        (".b", (), 4),
    ]


def test_scanner_skips_font_face_keyframes_and_statement_at_rules() -> None:
    css = (
        '@import "x.css";\n@font-face { font-family: X; src: url(x) }\n'
        "@keyframes k { from { top: 0 } to { top: 1px } }\n.z { top: 2px }"
    )
    assert [r.selector for r in scan_css(css)] == [".z"]


def test_scanner_ignores_nested_rule_bodies_and_strips_important() -> None:
    (rule,) = scan_css(".a { color: red !important; &:hover { color: blue } top: 0 }")
    assert [(d.prop, d.value) for d in rule.declarations] == [
        ("color", "red"),
        ("top", "0"),
    ]


def test_scanner_last_declaration_wins_and_tolerates_empty_or_broken_input() -> None:
    (rule,) = scan_css("a { top: 1px; top: 2px }")
    last = rule.last("top")
    assert last is not None and last.value == "2px"
    assert rule.last("left") is None
    assert scan_css("") == []
    assert scan_css("a { color: red") != [] and scan_css("}} ;; {") == []
