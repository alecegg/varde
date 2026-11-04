"""Independent lexical token reference for the A17 token-count audit.

This module shares no code with ``varde_code.quality_pass.facts``. It is a
hand-written lexical scanner (maximal munch over the characters of the source),
so it is an independent second opinion on the numbers the facts engine derives
from a tree-sitter parse.

Token definition applied to every fixture file (this is the reference method
recorded in ``README.md`` next to the fixtures):

* whitespace and comments are not tokens;
* an identifier/keyword, a numeric literal, one operator or punctuation mark,
  and one preprocessor directive keyword (``#include``, ``#define``, ...) are
  one token each; the scanner uses maximal munch, so ``==``, ``->``, ``:=`` and
  ``..`` are single tokens;
* a C-family character literal (``'a'``, ``'\\n'``) is one token;
* a string literal contributes ``min(32, ceil(len(content) / 8))`` tokens,
  where ``content`` is the source text between the delimiters with the prefix
  and suffix removed (for example ``b``/``r``/``f`` prefixes, ``@`` on C#
  verbatim strings, Rust ``r#...#`` and C++ ``R"delim(...)delim"`` markers).
  The same rule covers raw and interpolated strings: an interpolated string is
  one literal, and its embedded expression text is part of ``content``;
* a JavaScript-family regular expression literal is one token;
* after a C/C++ ``#include``/``#import``, the header name in angle brackets is
  one token (``#include <vector>`` is two tokens);
* in TSX, ``</`` is one token (the TypeScript scanner's ``LessThanSlashToken``)
  and a JSX text run - the maximal text up to the next ``<`` or ``{`` in an
  element's child position - is one token (``JsxText``).

The scanner is deliberately lexical, not semantic: it does not know types,
values or the language grammar. The TSX JSX rules use a small position machine
(mode, open-element return modes, tag and brace state); it handles nested
elements, fragments, self-closing tags (``/`` and ``>`` stay two tokens) and
inline ``{...}`` expressions, but not JSX entity references, which no fixture
uses. Construct scope is stated next to the fixtures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceToken:
    """One token in the reference stream: kind, source text and token weight."""

    kind: str
    text: str
    weight: int


@dataclass(frozen=True)
class LexRules:
    """Per-language lexical switches for :func:`reference_token_count`."""

    line_comments: tuple[str, ...] = ("//",)
    block_comments: tuple[tuple[str, str], ...] = (("/*", "*/"),)
    nested_block: bool = False
    preprocessor: bool = False
    triple_quote: bool = False
    python_prefixes: bool = False
    backtick_string: bool = False
    single_quote_is_char: bool = False
    rust_lifetime: bool = False
    rust_raw: bool = False
    cpp_raw: bool = False
    cpp_prefixes: bool = False
    at_dollar_prefix: bool = False
    dollar_identifiers: bool = False
    regex_literal: bool = False
    jsx: bool = False


_COMMON_OPERATORS: tuple[str, ...] = (
    "===",
    "!==",
    "&&=",
    "||=",
    "??=",
    "<<=",
    ">>=",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
    "->",
    "=>",
    "+",
    "-",
    "*",
    "/",
    "%",
    "=",
    "<",
    ">",
    "!",
    "&",
    "|",
    "^",
    "~",
    "?",
    ":",
    ";",
    ",",
    ".",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "@",
    "#",
    "$",
)
_EXTRA_OPERATORS: dict[str, tuple[str, ...]] = {
    "python": ("**=", "//=", "**", "//", ":=", "..."),
    "typescript": (
        ">>>=",
        "**=",
        "**",
        "..=",
        "...",
        "..",
        "??",
        "?.",
        ">>>",
    ),
    "tsx": (
        ">>>=",
        "**=",
        "**",
        "..=",
        "...",
        "..",
        "??",
        "?.",
        ">>>",
    ),
    "javascript": (
        ">>>=",
        "**=",
        "**",
        "..=",
        "...",
        "..",
        "??",
        "?.",
        ">>>",
    ),
    "java": (">>>", "::", "..."),
    "go": (":=", "<-", "&^", "..."),
    "rust": ("..=", "..", "::", "..."),
    "csharp": ("..=", "..", "?.", "??", "..."),
    "cpp": ("->*", "##", "::", "..."),
}


def _operators_for(language: str) -> tuple[str, ...]:
    operators = _COMMON_OPERATORS + _EXTRA_OPERATORS.get(language, ())
    return tuple(sorted(set(operators), key=len, reverse=True))


_OPERATORS = {language: _operators_for(language) for language in _EXTRA_OPERATORS}


_RULES: dict[str, LexRules] = {
    "python": LexRules(
        line_comments=("#",),
        block_comments=(),
        triple_quote=True,
        python_prefixes=True,
    ),
    "typescript": LexRules(
        dollar_identifiers=True, backtick_string=True, regex_literal=True
    ),
    "tsx": LexRules(
        dollar_identifiers=True, backtick_string=True, regex_literal=True, jsx=True
    ),
    "javascript": LexRules(
        dollar_identifiers=True, backtick_string=True, regex_literal=True
    ),
    "java": LexRules(triple_quote=True, single_quote_is_char=True),
    "go": LexRules(backtick_string=True, single_quote_is_char=True),
    "rust": LexRules(
        nested_block=True,
        single_quote_is_char=True,
        rust_lifetime=True,
        rust_raw=True,
    ),
    "csharp": LexRules(
        single_quote_is_char=True, at_dollar_prefix=True, triple_quote=True
    ),
    "cpp": LexRules(
        preprocessor=True,
        single_quote_is_char=True,
        cpp_raw=True,
        cpp_prefixes=True,
    ),
}

# Longest first so maximal munch picks the longest operator.

_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+"
    r"|0[bB][01_]+"
    r"|0[oO][0-7_]+"
    r"|(?:\d[\d_]*(?:\.[\d_]+)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?"
)
_NUMBER_SUFFIX = re.compile(r"[fFlLuUdDmMnN]\d*")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENTIFIER_DOLLAR = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_DIRECTIVE = re.compile(r"#[A-Za-z_]+")
_PYTHON_PREFIX = re.compile(r"[rRbBuUfF]{1,2}")
_CPP_PREFIX = re.compile(r"(?:u8|u|U|L)?")
_RUST_RAW = re.compile(r"b?r(#*)\"")
_RUST_CHAR = re.compile(r"'(?:\\.|[^\\'\n])'")
_AT_DOLLAR = ("@$", "$@", "@", "$")

# A ``<`` opens a JSX element only where an expression can start; after an
# identifier, literal or closing bracket it is a comparison or a type argument.
_JSX_OPERATORS = frozenset(
    {"(", "[", "{", ",", "=", "=>", ":", "?", "&&", "||", "??", "!", "..."}
)
_JSX_KEYWORDS = frozenset({"return", "yield", "await"})


@dataclass
class _JsxState:
    """TSX JSX position: mode, element return modes, tag and brace state."""

    mode: str = "code"
    returns: list[tuple[str, int]] = field(default_factory=list)
    in_tag: bool = False
    closing: bool = False
    self_closing: bool = False
    tag_braces: int = 0
    tag_return: tuple[str, int] = ("code", 0)
    expression_braces: int = 0


def _jsx_step(
    text: str, index: int, tokens: list[ReferenceToken], state: _JsxState
) -> int | None:
    """Append one JSX token when ``index`` starts one; return the next index."""
    char = text[index]
    if char.isspace():
        return None
    if state.in_tag:
        return _jsx_tag_step(text, index, tokens, state)
    if state.mode != "code":
        return _jsx_child_step(text, index, tokens, state, char)
    if char == "<" and _jsx_starts(tokens):
        return _jsx_open_tag(text, index, tokens, state)
    return None


def _jsx_child_step(
    text: str,
    index: int,
    tokens: list[ReferenceToken],
    state: _JsxState,
    char: str,
) -> int | None:
    """Handle a text or inline-expression position inside a JSX element."""
    if state.mode == "text":
        if char == "{":
            state.mode = "expr"
            state.expression_braces = 1
            return None
        if char == "<":
            return _jsx_open_tag(text, index, tokens, state)
        end = index
        while end < len(text) and text[end] not in "<{":
            end += 1
        tokens.append(ReferenceToken("jsx_text", text[index:end].strip(), 1))
        return end
    if char == "{":
        state.expression_braces += 1
    elif char == "}":
        state.expression_braces -= 1
        if state.expression_braces == 0:
            state.mode = "text"
    elif char == "<" and _jsx_starts(tokens):
        return _jsx_open_tag(text, index, tokens, state)
    return None


def _jsx_tag_step(
    text: str, index: int, tokens: list[ReferenceToken], state: _JsxState
) -> int | None:
    """Update tag brace state and end the tag at a top-level ``>``."""
    char = text[index]
    if char == "{":
        state.tag_braces += 1
        return None
    if char == "}":
        state.tag_braces = max(0, state.tag_braces - 1)
        return None
    if char == "/" and text.startswith("/>", index):
        state.self_closing = True
        return None
    if char == ">" and state.tag_braces == 0:
        tokens.append(ReferenceToken("operator", ">", 1))
        _jsx_close_tag(state)
        return index + 1
    return None


def _jsx_open_tag(
    text: str, index: int, tokens: list[ReferenceToken], state: _JsxState
) -> int:
    if text.startswith("</", index):
        tokens.append(ReferenceToken("operator", "</", 1))
        state.closing = True
        end = index + 2
    else:
        tokens.append(ReferenceToken("operator", "<", 1))
        state.closing = False
        end = index + 1
    state.in_tag = True
    state.self_closing = False
    state.tag_braces = 0
    state.tag_return = (state.mode, state.expression_braces)
    return end


def _jsx_close_tag(state: _JsxState) -> None:
    state.in_tag = False
    if state.self_closing:
        state.mode, state.expression_braces = state.tag_return
    elif state.closing:
        state.mode, state.expression_braces = (
            state.returns.pop() if state.returns else ("code", 0)
        )
    else:
        state.returns.append(state.tag_return)
        state.mode = "text"
        state.expression_braces = 0
    state.closing = False
    state.self_closing = False
    state.tag_braces = 0


def _jsx_starts(tokens: list[ReferenceToken]) -> bool:
    """Decide whether a ``<`` opens a JSX element, using the previous token."""
    if not tokens:
        return True
    previous = tokens[-1]
    if previous.kind == "operator":
        return previous.text in _JSX_OPERATORS
    if previous.kind == "word":
        return previous.text in _JSX_KEYWORDS
    return False


def reference_token_count(source: str | bytes, language: str) -> int:
    """Count code tokens in ``source`` using the documented lexical definition."""
    return sum(token.weight for token in reference_tokens(source, language))


def reference_tokens(source: str | bytes, language: str) -> list[ReferenceToken]:
    """Return the reference token stream for ``source`` in ``language``."""
    text = (
        source.decode("utf-8-sig", errors="replace")
        if isinstance(source, bytes)
        else source
    )
    rules = _rules_for(language)
    operators = _OPERATORS.get(language, _operators_for(language))
    tokens: list[ReferenceToken] = []
    jsx = _JsxState()
    index = 0
    while index < len(text):
        char = text[index]
        if rules.jsx and (advance := _jsx_step(text, index, tokens, jsx)) is not None:
            index = advance
            continue
        if char.isspace():
            index += 1
            continue
        if rules.preprocessor and char == "#":
            index, directive = _preprocessor_tokens(text, index)
            tokens.extend(directive)
            continue
        line_end = _line_comment_at(text, index, rules)
        if line_end is not None:
            index = line_end
            continue
        block_end = _block_comment_at(text, index, rules)
        if block_end is not None:
            index = block_end
            continue
        if rules.regex_literal and char == "/" and _regex_starts(tokens):
            regex = _regex_literal(text, index)
            if regex is not None:
                end, text_end = regex
                tokens.append(ReferenceToken("regex", text[index:text_end], 1))
                index = end
                continue
        literal = _string_at(text, index, rules)
        if literal is not None:
            end, weight, kind = literal
            tokens.append(ReferenceToken(kind, text[index:end], weight))
            index = end
            continue
        number_end = _number_at(text, index)
        if number_end is not None:
            tokens.append(ReferenceToken("number", text[index:number_end], 1))
            index = number_end
            continue
        if _identifier_start(char, rules):
            end = _identifier_end(text, index, rules)
            tokens.append(ReferenceToken("word", text[index:end], 1))
            index = end
            continue
        end = index + _operator_length(text, index, operators)
        tokens.append(ReferenceToken("operator", text[index:end], 1))
        index = end
    return tokens


def _rules_for(language: str) -> LexRules:
    try:
        return _RULES[language]
    except KeyError as error:
        raise ValueError(f"no reference lexer rules for {language!r}") from error


def _line_comment_at(text: str, index: int, rules: LexRules) -> int | None:
    for marker in rules.line_comments:
        if text.startswith(marker, index):
            end = text.find("\n", index)
            return len(text) if end < 0 else end
    return None


def _block_comment_at(text: str, index: int, rules: LexRules) -> int | None:
    for opener, closer in rules.block_comments:
        if not text.startswith(opener, index):
            continue
        if not rules.nested_block:
            end = text.find(closer, index + len(opener))
            return len(text) if end < 0 else end + len(closer)
        depth = 1
        cursor = index + len(opener)
        while cursor < len(text) and depth:
            if text.startswith(opener, cursor):
                depth += 1
                cursor += len(opener)
            elif text.startswith(closer, cursor):
                depth -= 1
                cursor += len(closer)
            else:
                cursor += 1
        return cursor
    return None


def _preprocessor_tokens(text: str, index: int) -> tuple[int, list[ReferenceToken]]:
    """Return (end, tokens) for one ``#``-directive occurrence."""
    match = _DIRECTIVE.match(text, index)
    if match is None:
        return index + 1, [ReferenceToken("operator", "#", 1)]
    tokens = [ReferenceToken("preprocessor", match.group(0), 1)]
    end = match.end()
    if match.group(0) in {"#include", "#import"}:
        cursor = end
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        if cursor < len(text) and text[cursor] == "<":
            close = text.find(">", cursor)
            end = len(text) if close < 0 else close + 1
            tokens.append(ReferenceToken("preprocessor", text[cursor:end], 1))
    return end, tokens


def _identifier_start(char: str, rules: LexRules) -> bool:
    if rules.dollar_identifiers and char == "$":
        return True
    return char.isalpha() or char == "_"


def _identifier_end(text: str, index: int, rules: LexRules) -> int:
    pattern = _IDENTIFIER_DOLLAR if rules.dollar_identifiers else _IDENTIFIER
    match = pattern.match(text, index)
    return match.end() if match is not None else index + 1


def _number_at(text: str, index: int) -> int | None:
    match = _NUMBER.match(text, index)
    if match is None:
        return None
    end = match.end()
    suffix = _NUMBER_SUFFIX.match(text, end)
    if suffix is not None:
        end = suffix.end()
    return end


def _operator_length(text: str, index: int, operators: tuple[str, ...]) -> int:
    for operator in operators:
        if text.startswith(operator, index):
            return len(operator)
    return 1


_REGEX_KEYWORDS = frozenset(
    {
        "await",
        "case",
        "delete",
        "do",
        "else",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "typeof",
        "void",
        "yield",
    }
)


def _regex_starts(tokens: list[ReferenceToken]) -> bool:
    """Decide whether a ``/`` begins a regex literal, using the previous token."""
    if not tokens:
        return True
    previous = tokens[-1]
    if previous.kind == "word":
        return previous.text in _REGEX_KEYWORDS
    if previous.kind == "operator":
        return previous.text not in {")", "]", "}", "++", "--"}
    return False


def _regex_literal(text: str, index: int) -> tuple[int, int] | None:
    """Return (end, literal end) for a ``/.../flags`` regex literal."""
    cursor = index + 1
    in_class = False
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "\n":
            return None
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            end = cursor + 1
            while end < len(text) and (text[end].isalpha() or text[end] == "_"):
                end += 1
            return end, end
        cursor += 1
    return None


def _string_at(text: str, index: int, rules: LexRules) -> tuple[int, int, str] | None:
    """Return (end, weight, kind) for the literal starting at ``index``."""
    if rules.backtick_string and text[index] == "`":
        end = _find_close(text, index + 1, "`", escaped=True)
        return _literals(end, index + 1)
    if rules.rust_raw:
        raw = _rust_raw_string(text, index)
        if raw is not None:
            return raw
        if text.startswith('b"', index):
            end = _find_close(text, index + 2, '"', escaped=True)
            return _literals(end, index + 2)
    if rules.cpp_raw:
        raw = _cpp_raw_string(text, index)
        if raw is not None:
            return raw
    if rules.at_dollar_prefix:
        csharp = _csharp_string(text, index)
        if csharp is not None:
            return csharp
    if rules.python_prefixes:
        python_string = _python_string(text, index, rules)
        if python_string is not None:
            return python_string
    if (
        rules.cpp_prefixes
        and (prefix := _CPP_PREFIX.match(text, index)) is not None
        and prefix.end() > index
    ):
        prefixed = _cpp_prefixed_string(text, index)
        if prefixed is not None:
            return prefixed
    return _plain_or_char_string(text, index, rules)


def _literals(end: int | None, start: int) -> tuple[int, int, str] | None:
    """Build a string token for content in ``text[start:end]``."""
    if end is None:
        return None
    return end + 1, _weight(end - start), "string"


def _plain_or_char_string(
    text: str, index: int, rules: LexRules
) -> tuple[int, int, str] | None:
    char = text[index]
    if char not in {"'", '"'}:
        return None
    if char == "'" and rules.single_quote_is_char:
        char_match = _RUST_CHAR.match(text, index)
        if char_match is not None:
            return char_match.end(), 1, "char"
        if rules.rust_lifetime:
            return index + 1, 1, "operator"
        return None
    quote = char
    if rules.triple_quote and text.startswith(quote * 3, index):
        end = _find_close(text, index + 3, quote * 3, escaped=False)
        return _triple(end, index + 3)
    end = _find_close(text, index + 1, quote, escaped=True)
    return _quoted(end, index + 1)


def _triple(end: int | None, start: int) -> tuple[int, int, str] | None:
    if end is None:
        return None
    return end + 3, _weight(end - start), "string"


def _quoted(end: int | None, start: int) -> tuple[int, int, str] | None:
    if end is None:
        return None
    return end + 1, _weight(end - start), "string"


def _python_string(
    text: str, index: int, rules: LexRules
) -> tuple[int, int, str] | None:
    prefix = _PYTHON_PREFIX.match(text, index)
    start = prefix.end() if prefix is not None else index
    if start >= len(text) or text[start] not in {"'", '"'}:
        return None
    quote = text[start]
    if rules.triple_quote and text.startswith(quote * 3, start):
        end = _find_close(text, start + 3, quote * 3, escaped=False)
        return _triple(end, start + 3)
    end = _find_close(text, start + 1, quote, escaped=True)
    return _quoted(end, start + 1)


def _cpp_prefixed_string(text: str, index: int) -> tuple[int, int, str] | None:
    prefix = _CPP_PREFIX.match(text, index)
    if prefix is None:
        return None
    start = prefix.end()
    if start >= len(text) or text[start] != '"':
        return None
    end = _find_close(text, start + 1, '"', escaped=True)
    return _quoted(end, start + 1)


def _rust_raw_string(text: str, index: int) -> tuple[int, int, str] | None:
    match = _RUST_RAW.match(text, index)
    if match is None:
        return None
    opener = match.end()
    closer = '"' + match.group(1)
    end = text.find(closer, opener)
    if end < 0:
        return None
    return end + len(closer), _weight(end - opener), "string"


def _cpp_raw_string(text: str, index: int) -> tuple[int, int, str] | None:
    prefix = _CPP_PREFIX.match(text, index)
    if prefix is None:
        return None
    start = prefix.end()
    if not text.startswith('R"', start):
        return None
    delimiter_start = start + 2
    paren = text.find("(", delimiter_start)
    if paren < 0:
        return None
    delimiter = text[delimiter_start:paren]
    end = text.find(")" + delimiter + '"', paren)
    if end < 0:
        return None
    return end + len(delimiter) + 2, _weight(end - (paren + 1)), "string"


def _csharp_string(text: str, index: int) -> tuple[int, int, str] | None:
    for prefix in _AT_DOLLAR:
        if not text.startswith(prefix, index):
            continue
        start = index + len(prefix)
        if start >= len(text) or text[start] != '"':
            continue
        if text.startswith('"""', start):
            end = text.find('"""', start + 3)
            return _triple(end, start + 3)
        end = _find_close(text, start + 1, '"', escaped=True)
        return _quoted(end, start + 1)
    return None


def _find_close(text: str, start: int, closer: str, *, escaped: bool) -> int | None:
    cursor = start
    while cursor < len(text):
        if escaped and text[cursor] == "\\":
            cursor += 2
            continue
        if text.startswith(closer, cursor):
            return cursor
        cursor += 1
    return None


def _weight(content_length: int) -> int:
    return min(32, (content_length + 7) // 8)
