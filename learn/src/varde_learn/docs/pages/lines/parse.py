"""Parse `ui` fence text into statements (pure; stdlib only; see grammar.py)."""

import json
import math
import re
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field

from varde_learn.docs.pages.blocks.check import ID_RULE

MAX_DEPTH = 32
_WORD = re.compile(r"[A-Za-z0-9_-]+")
_COMPONENT = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_PROP = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_STATEMENT_START = re.compile(r"^[ \t]*[A-Za-z0-9_-]+[ \t]*=", re.MULTILINE)
_LITERALS = {"true": True, "false": False, "null": None}


@dataclass(frozen=True)
class Ref:
    """Reference to an earlier statement id."""

    id: str


@dataclass(frozen=True)
class Statement:
    id: str
    component: str
    props: dict[str, object]
    line: int  # 1-based line of the id
    end_line: int


@dataclass(frozen=True)
class ParseError:
    line: int  # 1-based
    rule: str
    message: str

    def text(self) -> str:
        return f"line {self.line}: {self.rule}: {self.message}"


@dataclass
class ParseResult:
    statements: list[Statement] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    pending: str = ""  # cut-off tail of the last statement (partial only)


class _Fail(Exception):
    def __init__(self, pos: int, rule: str, message: str) -> None:
        super().__init__(message)
        self.pos, self.rule, self.message = pos, rule, message


class _Cutoff(Exception):
    """Input ended inside a statement."""


class _Cursor:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def line(self, pos: int) -> int:
        return bisect_right(self.starts, pos)

    def fail(self, rule: str, message: str, pos: int | None = None) -> _Fail:
        return _Fail(self.pos if pos is None else pos, rule, message)

    def peek(self) -> str:
        if self.pos >= len(self.text):
            raise _Cutoff
        return self.text[self.pos]

    def skip(self) -> None:
        """Skip whitespace and comments; may reach end of text."""
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch == "#":
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end
            elif ch.isspace():
                self.pos += 1
            else:
                return

    def expect(self, ch: str, what: str) -> None:
        self.skip()
        if self.peek() != ch:
            raise self.fail("syntax", f"expected {what}, found {self.text[self.pos]!r}")
        self.pos += 1

    def match(self, pattern: re.Pattern[str]) -> str | None:
        m = pattern.match(self.text, self.pos)
        if m is None:
            return None
        self.pos = m.end()
        return m.group()


def _decode_string(cur: _Cursor, start: int, end: int) -> str:
    try:
        value = json.loads(cur.text[start:end])
    except ValueError as exc:
        if "control character" in str(exc):
            message = "raw control character in string (use an escape such as \\t)"
        else:
            message = f"bad string escape: {exc}"
        raise cur.fail("syntax", message, start) from None
    if any("\ud800" <= ch <= "\udfff" for ch in value):
        raise cur.fail("syntax", "lone surrogate escape in string", start)
    return value


def _string(cur: _Cursor) -> str:
    start = cur.pos
    text, i = cur.text, cur.pos + 1
    while i < len(text) and text[i] != '"':
        if text[i] == "\n":
            raise cur.fail("unterminated", "string is not closed on its line", start)
        i += 2 if text[i] == "\\" else 1
    if i >= len(text):
        raise _Cutoff
    cur.pos = i + 1
    return _decode_string(cur, start, i + 1)


_NUMBER_TAIL = re.compile(r"[.eE][+-]?\Z")


def _number(cur: _Cursor) -> int | float:
    start = cur.pos
    if cur.text[start:] == "-":
        raise _Cutoff
    raw = cur.match(_NUMBER)
    if raw is None:
        raise cur.fail("syntax", "bad number", start)
    if cur.pos >= len(cur.text) or _NUMBER_TAIL.match(cur.text, cur.pos):
        raise _Cutoff
    if "." not in raw and "e" not in raw and "E" not in raw:
        return _int(cur, raw, start)
    value = float(raw)
    if not math.isfinite(value):
        raise cur.fail("syntax", "number is out of range", start)
    return value


def _int(cur: _Cursor, raw: str, start: int) -> int:
    try:
        return int(raw)
    except ValueError:
        raise cur.fail("syntax", "integer has too many digits", start) from None


def _array(cur: _Cursor, depth: int, seen: Mapping[str, int]) -> list[object]:
    cur.pos += 1
    items: list[object] = []
    while True:
        cur.skip()
        if cur.peek() == "]":
            cur.pos += 1
            return items
        items.append(_value(cur, depth + 1, seen))
        cur.skip()
        if cur.peek() == ",":
            cur.pos += 1
        elif cur.peek() != "]":
            raise cur.fail("syntax", "expected ',' or ']' in array")


def _key(cur: _Cursor) -> str:
    cur.skip()
    if cur.peek() == '"':
        return _string(cur)
    key = cur.match(_PROP)
    if key is None:
        raise cur.fail("syntax", "expected an object key")
    return key


def _object(cur: _Cursor, depth: int, seen: Mapping[str, int]) -> dict[str, object]:
    cur.pos += 1
    out: dict[str, object] = {}
    while True:
        cur.skip()
        if cur.peek() == "}":
            cur.pos += 1
            return out
        at = cur.pos
        key = _key(cur)
        if key in out:
            raise cur.fail("prop-duplicate", f"duplicate key '{key}'", at)
        cur.expect(":", "':' after key")
        out[key] = _value(cur, depth + 1, seen)
        cur.skip()
        if cur.peek() == ",":
            cur.pos += 1
        elif cur.peek() != "}":
            raise cur.fail("syntax", "expected ',' or '}' in object")


def _word(cur: _Cursor, seen: Mapping[str, int]) -> object:
    start = cur.pos
    word = cur.match(_WORD)
    if cur.pos >= len(cur.text):
        raise _Cutoff
    if word in _LITERALS:
        return _LITERALS[word]
    if word is None or not ID_RULE.match(word):
        raise cur.fail("syntax", f"unexpected {cur.text[start]!r}", start)
    if word not in seen:
        raise cur.fail("ref-unknown", f"'{word}' is not an earlier statement", start)
    return Ref(word)


def _value(cur: _Cursor, depth: int, seen: Mapping[str, int]) -> object:
    if depth > MAX_DEPTH:
        raise cur.fail("depth", f"nesting deeper than {MAX_DEPTH}")
    cur.skip()
    ch = cur.peek()
    if ch == '"':
        return _string(cur)
    if ch == "[":
        return _array(cur, depth, seen)
    if ch == "{":
        return _object(cur, depth, seen)
    if ch == "-" or ch.isdigit():
        return _number(cur)
    return _word(cur, seen)


def _props(cur: _Cursor, seen: Mapping[str, int]) -> dict[str, object]:
    props: dict[str, object] = {}
    while True:
        cur.skip()
        if cur.peek() == ")":
            cur.pos += 1
            return props
        at = cur.pos
        name = cur.match(_PROP)
        if name is None:
            raise cur.fail("syntax", f"expected a prop name, found {cur.peek()!r}")
        if name in props:
            raise cur.fail("prop-duplicate", f"duplicate prop '{name}'", at)
        cur.expect(":", "':' after prop name")
        props[name] = _value(cur, 1, seen)
        cur.skip()
        if cur.peek() == ",":
            cur.pos += 1
        elif cur.peek() != ")":
            raise cur.fail("syntax", "expected ',' or ')' after value")


def _rest_of_line_blank(cur: _Cursor) -> None:
    text = cur.text
    end = text.find("\n", cur.pos)
    rest = text[cur.pos : len(text) if end < 0 else end]
    if rest.strip() and not rest.lstrip().startswith("#"):
        raise cur.fail("trailing", "text after the closing ')'")


def _statement(cur: _Cursor, seen: dict[str, int]) -> Statement:
    start = cur.pos
    ident = cur.match(_WORD)
    if ident is None:
        raise cur.fail(
            "syntax", f"expected '<id> = Component(...)', found {cur.peek()!r}"
        )
    if ident in _LITERALS:
        raise cur.fail("id-invalid", f"id '{ident}' is a reserved literal", start)
    if not ID_RULE.match(ident):
        raise cur.fail(
            "id-invalid", f"id '{ident}' must match {ID_RULE.pattern}", start
        )
    if ident in seen:
        message = f"id '{ident}' is already used at line {seen[ident]}"
        raise cur.fail("id-duplicate", message, start)
    cur.expect("=", "'=' after the id")
    cur.skip()
    cur.peek()
    component = cur.match(_COMPONENT)
    if cur.pos >= len(cur.text):
        raise _Cutoff
    if component is None:
        raise cur.fail("syntax", "expected a component name after '='")
    cur.expect("(", "'(' after the component name")
    props = _props(cur, seen)
    _rest_of_line_blank(cur)
    return Statement(ident, component, props, cur.line(start), cur.line(cur.pos - 1))


def _recover(cur: _Cursor, error_pos: int) -> None:
    """Move to the next line that starts a statement, after the failing line."""
    end = cur.text.find("\n", error_pos)
    if end < 0:
        cur.pos = len(cur.text)
        return
    m = _STATEMENT_START.search(cur.text, end + 1)
    cur.pos = len(cur.text) if m is None else m.start()


def _swallowed_next_statement(cur: _Cursor, start: int, fail: _Fail) -> bool:
    """True when a syntax error sits on a later line that starts a statement."""
    fail_line = cur.line(fail.pos)
    if fail.rule != "syntax" or fail_line <= cur.line(start):
        return False
    return _STATEMENT_START.match(cur.text, cur.starts[fail_line - 1]) is not None


def parse_lines(text: str, *, partial: bool = False) -> ParseResult:
    """Parse statements; every error carries a 1-based line.

    With `partial=True` a statement cut off at the end of `text` is not an
    error: its text goes to `pending` and earlier statements are returned.
    """
    cur = _Cursor(text)
    result = ParseResult()
    seen: dict[str, int] = {}
    while True:
        cur.skip()
        if cur.pos >= len(text):
            return result
        start = cur.pos
        try:
            stmt = _statement(cur, seen)
        except _Cutoff:
            if partial:
                result.pending = text[start:]
            else:
                message = "statement is not closed before the end of the text"
                result.errors.append(
                    ParseError(cur.line(start), "unterminated", message)
                )
            return result
        except _Fail as fail:
            if _swallowed_next_statement(cur, start, fail):
                message = "statement is not closed before the next statement"
                line = cur.line(start)
                result.errors.append(ParseError(line, "unterminated", message))
                cur.pos = cur.starts[cur.line(fail.pos) - 1]
                continue
            result.errors.append(
                ParseError(cur.line(fail.pos), fail.rule, fail.message)
            )
            _recover(cur, fail.pos)
            continue
        seen[stmt.id] = stmt.line
        result.statements.append(stmt)
