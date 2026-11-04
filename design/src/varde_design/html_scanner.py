"""HTML scanner: text in, elements, text nodes and style sources out. Pure; no I/O.

Built on the stdlib HTMLParser. Elements keep tag, lowercase attributes, source
line, parent and children. Unclosed elements are closed at the next end tag of an
ancestor; stray end tags are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_TAGS = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)


@dataclass
class Element:
    index: int
    tag: str
    attrs: dict[str, str]
    line: int
    parent: int | None
    children: list[int] = field(default_factory=list)

    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()


@dataclass(frozen=True)
class TextNode:
    text: str
    line: int
    parent: int | None


@dataclass(frozen=True)
class StyleSource:
    """CSS text found in the document; line is where its first line sits."""

    css: str
    line: int
    owner: int | None = None


@dataclass
class Document:
    elements: list[Element] = field(default_factory=list)
    texts: list[TextNode] = field(default_factory=list)
    styles: list[StyleSource] = field(default_factory=list)
    has_doctype: bool = False

    def find(self, tag: str) -> list[Element]:
        return [e for e in self.elements if e.tag == tag]

    def next_sibling(self, element: Element) -> Element | None:
        if element.parent is None:
            siblings = [e.index for e in self.elements if e.parent is None]
        else:
            siblings = self.elements[element.parent].children
        position = siblings.index(element.index)
        later = siblings[position + 1 :]
        return self.elements[later[0]] if later else None

    def descendants_text(self, element: Element) -> str:
        """All text under element in source order, whitespace collapsed."""
        inside = _subtree(self, element.index)
        chunks = [n.text for n in self.texts if n.parent in inside]
        return " ".join(" ".join(chunks).split())


def _subtree(doc: Document, root: int) -> set[int]:
    seen, stack = set(), [root]
    while stack:
        index = stack.pop()
        seen.add(index)
        stack += doc.elements[index].children
    return seen


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc = Document()
        self.stack: list[int] = []

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> Element:
        parent = self.stack[-1] if self.stack else None
        values = {name.lower(): value or "" for name, value in attrs}
        element = Element(len(self.doc.elements), tag, values, self.getpos()[0], parent)
        self.doc.elements.append(element)
        if parent is not None:
            self.doc.elements[parent].children.append(element.index)
        style = values.get("style")
        if style:
            self.doc.styles.append(
                StyleSource(f"*{{{style}}}", element.line, element.index)
            )
        return element

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = self._open(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.append(element.index)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.doc.elements[self.stack[depth]].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        parent = self.stack[-1] if self.stack else None
        tag = self.doc.elements[parent].tag if parent is not None else ""
        line = self.getpos()[0]
        if tag == "style":
            self.doc.styles.append(StyleSource(data, line, parent))
        elif tag != "script" and data.strip():
            self.doc.texts.append(TextNode(data, line, parent))

    def handle_decl(self, decl: str) -> None:
        self.doc.has_doctype = decl.strip().lower().startswith("doctype")


def parse_html(text: str) -> Document:
    """Parse text into a Document; never raises on malformed markup."""
    builder = _Builder()
    builder.feed(text)
    builder.close()
    return builder.doc
