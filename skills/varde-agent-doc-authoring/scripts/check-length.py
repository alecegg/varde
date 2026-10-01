#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Flag long text in agent documents (criteria.md, Length limits).

Usage: check-length.py <skill-dir-or-file>...

A skill directory expands to its SKILL.md and references/**/*.md.
Units are prose blocks (consecutive paragraphs with only blank lines between)
and top-level list items with everything nested under them: WARN at 4-5
sentences, ERROR at 6+. Sections (text between headings):
WARN over 250 words, ERROR over 400. Prose share (words in prose blocks over
all non-code words, for files of 150+ words): WARN over 40%, ERROR over 60%. Also WARNs on an inline list (a prose
sentence of four or more comma-separated items, or three when any item runs
three or more words) and a lazy continuation (an
unindented line directly under a list item, which Markdown joins into it).
Exits 1 only on errors, 2 on bad input.
"""
import re
import sys
from pathlib import Path


UNIT_WARN, UNIT_ERROR = 4, 6
SECTION_WARN, SECTION_ERROR = 250, 400
PROSE_WARN, PROSE_ERROR, PROSE_MIN_WORDS = 40, 60, 150
ITEM = re.compile(r"(\s*)([-*+]|\d+[.)])\s+")
STRIP = [
    re.compile(r"`[^`]*`"),                              # inline code
    re.compile(r"\[([^\]]*)\]\([^)]*\)"),                # link targets
    re.compile(r"https?://\S+"),                         # URLs
    re.compile(r"\b(e\.g|i\.e|etc|vs|cf|approx)\.", re.I),
    re.compile(r"\bv?\d+(\.\d+)+\b"),                    # versions, decimals
    re.compile(r"[\w./-]+\.[A-Za-z]{1,5}\b"),            # file names and paths
]
HINTS = {"prose": "; steps or lists written as sentences?",
         "series": "; put one item per line under a lead-in"}
SENTENCE_END = re.compile(r"[.!?][)\"'*_]*(\s|$)")
SERIES = re.compile(r"(?:[^,;:.!?()]+,\s*){2,}[^,;:.!?()]*?\b(?:and|or)\b[^,;:.!?()]*")


def sentences(text):
    for pattern in STRIP:
        text = pattern.sub(lambda m: m.group(1) if m.lastindex else "x", text)
    return len(SENTENCE_END.findall(text))


def is_list_worthy(series):
    """Four or more items, or three when a later item runs three or more words.

    The first item is skipped for length: the match also holds the words that
    lead into the list.
    """
    items = [re.sub(r"^\s*(and|or)\s+", "", part).split() for part in series.split(",")]
    return len(items) >= 4 or max(len(words) for words in items[1:]) >= 3


def frontmatter_end(lines):
    """Index of the first body line; 0 when there is no frontmatter."""
    if not lines or lines[0].strip() != "---":
        return 0
    for n, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return n + 1
    return 0  # unclosed frontmatter: treat the file as body


def scan(path):
    """Yield (kind, line, size) for every unit and section.

    A top-level list item is one unit with everything indented under it:
    nested items, continuation paragraphs, and fenced code (not counted).
    """
    lines = open(path).read().split("\n")
    first = frontmatter_end(lines)
    fenced = False
    unit, unit_line, item_indent = [], 0, None
    section_words, section_line = 0, first + 1
    prose_words = total_words = 0

    def close_unit():
        nonlocal unit, item_indent
        if unit:
            text = " ".join(unit)
            yield "unit", unit_line, sentences(text)
            for series in SERIES.finditer(STRIP[0].sub("x", text)):
                if is_list_worthy(series.group(0)):
                    yield "series", unit_line, series.group(0).count(",") + 1
                    break
        unit, item_indent = [], None

    for n, line in enumerate(lines[first:], first + 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        inside_item = item_indent is not None and indent > item_indent
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            if not inside_item:
                yield from close_unit()
            continue
        if fenced:
            continue
        if not stripped:
            continue  # blank lines never end a unit; only structure does
        total_words += len(stripped.split())
        if stripped.startswith("#"):
            yield from close_unit()
            yield "section", section_line, section_words
            section_words, section_line = 0, n
            continue
        if stripped.startswith(("|", "<!--")):
            if not inside_item:
                yield from close_unit()
            continue
        section_words += len(stripped.split())
        item = ITEM.match(line)
        if inside_item:
            # A nested item is its own clause, so it never joins a series.
            unit.append("; " + line[item.end():] if item else stripped)
        elif item:
            yield from close_unit()
            unit, unit_line, item_indent = [line[item.end():]], n, indent
        elif unit and item_indent is None:
            unit.append(stripped)
            prose_words += len(stripped.split())
        else:
            yield from close_unit()
            unit, unit_line = [stripped.lstrip("> ")], n
            prose_words += len(stripped.split())
    yield from close_unit()
    yield "section", section_line, section_words
    if total_words >= PROSE_MIN_WORDS:
        yield "prose", first + 1, 100 * prose_words // total_words



def layout(path):
    """Yield (line, note) for lazy continuations and stray </content> lines."""
    lines = open(path).read().split("\n")
    fenced, previous_item = False, False
    first = frontmatter_end(lines)
    for n, line in enumerate(lines[first:], first + 1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced, previous_item = not fenced, False
            continue
        if fenced or not stripped or stripped.startswith(("#", "|", "<!--", "---")):
            previous_item = False
            continue
        if stripped == "</content>":
            yield n, "stray </content> line"
        item = ITEM.match(line)
        if previous_item and not item and not line[0].isspace():
            yield n, "lazy continuation; indent it under its item"
        previous_item = bool(item) or (previous_item and line[0].isspace())


def expand(arg):
    path = Path(arg)
    if path.is_dir():
        found = [path / "SKILL.md"] if (path / "SKILL.md").is_file() else []
        return found + sorted((path / "references").glob("**/*.md"))
    if path.is_file():
        return [path]
    print(f"check-length.py: no such file or directory: {arg}", file=sys.stderr)
    sys.exit(2)


def main(args):
    if not args:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    files = [f for arg in args for f in expand(arg)]
    if not files:
        print("check-length.py: no Markdown files found", file=sys.stderr)
        return 2
    limits = {"unit": (UNIT_WARN, UNIT_ERROR, "sentences"),
              "series": (0, 10**9, "items"),
              "section": (SECTION_WARN + 1, SECTION_ERROR + 1, "words"),
              "prose": (PROSE_WARN + 1, PROSE_ERROR + 1, "percent")}
    warnings = errors = 0
    for path in files:
        for kind, line, size in scan(path):
            warn_at, error_at, measure = limits[kind]
            label = {"series": "inline list", "prose": "prose share"}.get(kind, kind)
            hint = HINTS.get(kind, "")
            if size >= error_at:
                errors += 1
                print(f"ERROR {path}:{line} ({label}, {size} {measure}){hint}")
            elif size >= warn_at:
                warnings += 1
                print(f"WARN  {path}:{line} ({label}, {size} {measure}){hint}")
        for line, note in layout(path):
            warnings += 1
            print(f"WARN  {path}:{line} ({note})")
    print(f"{errors} error(s), {warnings} warning(s) across {len(files)} file(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
