"""HTML for the code panel: header, a line-numbered `<pre>`, server-side highlighting.

Also draws plain fenced markdown code. Highlighting never changes the text: every
token is a slice of the source, so stripping tags returns the escaped source.
The Copy button is added by `static/code.js`; the panel reads fine without it.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from varde_learn.docs.pages.blocks_render.common import esc
from varde_learn.docs.pages.blocks_render.svg import copy_attr

MAX_DIGIT_CLASS = 6
MAX_MARK_RANGES = 8
_TRIPLE_DQ = r'"""(?:[^"\\]|\\.|"(?!""))*"""'
_TRIPLE_SQ = r"'''(?:[^'\\]|\\.|'(?!''))*'''"
_TRIPLE = rf"[rbfuRBFU]{{0,2}}(?:{_TRIPLE_DQ}|{_TRIPLE_SQ})"
_DQ = r'"(?:[^"\\\n]|\\.)*"'
_SQ = r"'(?:[^'\\\n]|\\.)*'"
_NUMBER = r"\b(?:0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b"
_WORDS = {
    "python": """
        and as assert async await break class continue def del elif else except
        finally for from global if import in is lambda None nonlocal not or pass
        raise return True False try while with yield
""",
    "js": """
        async await break case catch class const continue default delete do else
        export extends finally for from function if import in instanceof interface
        let new null of return static super switch this throw true false try type
        typeof undefined var void while yield
""",
    "json": """
        true false null
""",
    "shell": """
        case do done elif else esac export fi for function if in local return then
        until while
""",
}
_COMMENTS = {
    "python": r"#[^\n]*",
    "js": r"//[^\n]*|/\*(?s:.*?)\*/",
    "json": None,
    "shell": r"(?<!\S)#[^\n]*",
}
_STRINGS = {
    "python": f"{_TRIPLE}|(?:[rbfuRBFU]{{0,2}}(?:{_DQ}|{_SQ}))",
    "js": rf"{_DQ}|{_SQ}|`(?:[^`\\]|\\.)*`",
    "json": _DQ,
    "shell": rf"{_DQ}|'[^'\n]*'",
}
ALIASES = {
    "python": "python",
    "py": "python",
    "js": "js",
    "javascript": "js",
    "jsx": "js",
    "ts": "js",
    "typescript": "js",
    "tsx": "js",
    "json": "json",
    "sh": "shell",
    "bash": "shell",
    "shell": "shell",
    "zsh": "shell",
}
CLASS_OF = {"comment": "c", "string": "s", "number": "n", "word": "k"}


def _grammar(family: str) -> re.Pattern[str]:
    parts = [
        f"(?P<comment>{_COMMENTS[family]})" if _COMMENTS[family] else None,
        f"(?P<string>{_STRINGS[family]})",
        f"(?P<number>{_NUMBER})",
        r"(?P<word>\b(?:" + "|".join(_WORDS[family].split()) + r")\b)",
    ]
    return re.compile("|".join(p for p in parts if p))


GRAMMARS = {family: _grammar(family) for family in _WORDS}


def tokenize(source: str, language: str) -> list[tuple[str, str]]:
    """Split source into (kind, text) pieces that concatenate to the source.

    The kind is "" for plain text. An unknown language is one plain piece.
    """
    family = ALIASES.get(language.lower())
    if family is None:
        return [("", source)]
    pieces: list[tuple[str, str]] = []
    end = 0
    for match in GRAMMARS[family].finditer(source):
        if match.start() > end:
            pieces.append(("", source[end : match.start()]))
        pieces.append((str(match.lastgroup), match.group()))
        end = match.end()
    if end < len(source):
        pieces.append(("", source[end:]))
    return pieces


def split_lines(pieces: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Cut pieces at newlines so each line holds its own whole pieces."""
    lines: list[list[tuple[str, str]]] = [[]]
    for kind, text in pieces:
        first, *rest = text.split("\n")
        if first:
            lines[-1].append((kind, first))
        lines.extend([(kind, part)] if part else [] for part in rest)
    return lines


def line_html(pieces: list[tuple[str, str]]) -> str:
    return "".join(
        f'<span class="vd-code-{CLASS_OF[kind]}">{esc(text)}</span>'
        if kind
        else esc(text)
        for kind, text in pieces
    )


def _shown(
    source: str, window: object, language: str
) -> tuple[list[list[tuple[str, str]]], int]:
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = split_lines(tokenize(text, language))
    if len(lines) > 1 and not lines[-1]:
        lines.pop()  # a closing newline does not start another line
    first, last = 1, len(lines)
    if isinstance(window, list) and len(window) == 2:
        first = min(max(int(window[0]), 1), len(lines))
        last = min(max(int(window[1]), first), len(lines))
    return lines[first - 1 : last], first


def marked_lines(mark: object, first: int, last: int) -> set[int]:
    """Marked line numbers inside [first, last]; ranges are clipped, not expanded."""
    found: set[int] = set()
    for item in mark if isinstance(mark, list) else []:
        low, high = (item, item) if isinstance(item, int) else (item[0], item[1])
        found.update(range(max(low, first), min(high, last) + 1))
    return found


def _runs(numbers: list[int]) -> Iterator[tuple[int, int]]:
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n != prev + 1:
            yield start, prev
            start = n
        prev = n
    yield start, prev


def marks_note(marked: set[int]) -> str:
    """Text for the header: which lines are marked, in words."""
    if not marked:
        return ""
    runs = [f"{a}" if a == b else f"{a}-{b}" for a, b in _runs(sorted(marked))]
    more = len(runs) - MAX_MARK_RANGES
    shown = ", ".join(runs[:MAX_MARK_RANGES]) + (
        f" and {more} more" if more > 0 else ""
    )
    word = "Marked line" if len(marked) == 1 else "Marked lines"
    return f"{word} {shown}"


def _line_span(number: int, body: str, marked: bool) -> str:
    mark = ' data-mark="1"' if marked else ""
    return f'<span class="vd-code-line" data-line="{number}"{mark}>{body}\n</span>'


def _class_name(language: str) -> str:
    return re.sub(r"[^A-Za-z0-9_+#.-]", "", language)


@dataclass(frozen=True)
class Panel:
    """What the author chose besides the source and language."""

    title: str = ""
    window: object = None  # [from, to] source lines to show
    wrap: bool = False
    numbers: bool = True
    mark: object = None  # line numbers and [from, to] ranges to call out


def render_code_panel(
    source: str, language: str = "", panel: Panel | None = None
) -> str:
    panel = panel or Panel()
    title = panel.title
    lines, first = _shown(source, panel.window, language)
    last = first + len(lines) - 1
    marked = marked_lines(panel.mark, first, last)
    body = "".join(
        _line_span(first + i, line_html(line), first + i in marked)
        for i, line in enumerate(lines)
    )
    raw = "\n".join("".join(text for _, text in line) for line in lines)
    digits = min(len(str(last)), MAX_DIGIT_CLASS)
    classes = f"vb code vd-code-panel vd-code vd-code-d{digits}"
    classes += " vd-code-wrap" if panel.wrap else ""
    classes += "" if panel.numbers else " vd-code-nonum"
    label = language or "text"
    caption = f'<span class="vd-code-title">{esc(title)}</span>' if title else ""
    note = marks_note(marked)
    note_html = f'<span class="vd-code-marks">{esc(note)}</span>' if note else ""
    region = f"{title or 'Code'}, {label}, lines {first} to {last}"
    code_class = f' class="language-{_class_name(language)}"' if language else ""
    return (
        f'<figure class="{classes}"{copy_attr(raw)}>'
        f'<figcaption class="vd-code-head">{caption}'
        f'<span class="vd-code-lang">{esc(label)}</span>{note_html}</figcaption>'
        f'<div class="vd-code-scroll" role="region" aria-label="{esc(region)}"'
        ' tabindex="0">'
        f'<pre class="vd-code-pre"><code{code_class}>{body}</code></pre></div></figure>'
    )


def render_code(data: dict[str, object]) -> str:
    panel = Panel(
        title=str(data.get("title", "")),
        window=data.get("lines"),
        wrap=data.get("wrap") is True,
        numbers=data.get("numbers") is not False,
        mark=data.get("mark"),
    )
    return render_code_panel(str(data["source"]), str(data["language"]), panel)
