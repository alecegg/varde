from varde_design.css_scanner import scan_css
from varde_design.html_scanner import parse_html
from varde_design.html_style import element_style, selector_matches

PAGE = (
    "<!doctype html>\n<html lang=en>\n<head><style>\n.a { color: red }\n"
    "</style></head>\n"
    "<body>\n<p class='x y' style='margin: 0'>hi\n there</p>\n"
    "<div>\n\n<span>t</span><br><img src=a.png></div>\n"
    "<script>var x = '<p>';</script>\n"
)


def test_elements_lines_and_parents() -> None:
    doc = parse_html(PAGE)
    tags = [(e.tag, e.line) for e in doc.elements]
    assert ("html", 2) in tags and ("p", 7) in tags and ("span", 11) in tags
    span = doc.find("span")[0]
    assert doc.elements[span.parent or 0].tag == "div"
    assert doc.has_doctype


def test_attributes_lowercased_and_classes_split() -> None:
    doc = parse_html("<P CLASS='x y' Data-A=1 hidden>")
    p = doc.elements[0]
    assert p.tag == "p"
    assert p.attrs == {"class": "x y", "data-a": "1", "hidden": ""}
    assert p.classes() == ["x", "y"]


def test_text_nodes_skip_script_and_style_and_keep_line() -> None:
    doc = parse_html(PAGE)
    assert [(t.text.strip(), t.line) for t in doc.texts] == [
        ("hi\n there", 7),
        ("t", 11),
    ]


def test_style_sources_block_and_attribute_with_start_line() -> None:
    doc = parse_html(PAGE)
    block, inline = doc.styles
    assert block.css == "\n.a { color: red }\n" and block.line == 3
    assert inline.css == "*{margin: 0}" and inline.line == 7


def test_void_tags_do_not_swallow_siblings() -> None:
    doc = parse_html("<div><img src=a><br><p>x</p></div>")
    div = doc.find("div")[0]
    assert [doc.elements[i].tag for i in div.children] == ["img", "br", "p"]


def test_stray_end_tag_and_unclosed_elements_do_not_raise() -> None:
    doc = parse_html("</b><div><p>one<p>two</div><span>")
    assert [e.tag for e in doc.elements] == ["div", "p", "p", "span"]


def test_next_sibling_and_descendants_text() -> None:
    doc = parse_html("<div><span>a <b>b</b></span><h2>t</h2></div><p>z</p>")
    span = doc.find("span")[0]
    assert doc.next_sibling(span) is doc.find("h2")[0]
    assert doc.next_sibling(doc.find("h2")[0]) is None
    assert doc.descendants_text(span) == "a b"
    assert doc.next_sibling(doc.find("div")[0]) is doc.find("p")[0]


def test_selector_matching_boundaries() -> None:
    p = parse_html("<p id=i class='a b'>").elements[0]
    assert selector_matches("p", p) and selector_matches(".a.b", p)
    assert selector_matches("p#i", p) and selector_matches(".z .a", p)
    assert not selector_matches(".c", p) and not selector_matches("p:hover", p)
    assert not selector_matches("h1 + .a", p) and not selector_matches("*", p)


def test_element_style_later_rule_and_inline_win() -> None:
    p = parse_html("<p class=a>").elements[0]
    rules = scan_css(".a { color: red; size: 1 } p { color: blue }")
    inline = scan_css("*{size: 2}")[0]
    assert element_style(p, rules, inline) == {"color": "blue", "size": "2"}
    assert element_style(p, rules, None)["size"] == "1"
