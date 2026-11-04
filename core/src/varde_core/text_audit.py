"""Length and layout audit for Markdown agent documents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

UNIT_WARN, UNIT_ERROR = 4, 6
SENTENCE_WARN = 25
SECTION_WARN, SECTION_ERROR = 250, 400
PROSE_WARN, PROSE_ERROR, PROSE_MIN_WORDS = 40, 60, 150
HINT_PROSE = "; steps or lists written as sentences?"
HINT_SERIES = "; put one item per line under a lead-in"
HOW_RUN_MIN = 3
ORCHESTRATING_SKILLS = frozenset({"varde-orchestrate", "varde-swarm"})
_IMPERATIVES = frozenset(
    {
        "add",
        "apply",
        "build",
        "check",
        "commit",
        "compare",
        "confirm",
        "create",
        "delete",
        "edit",
        "fix",
        "load",
        "open",
        "record",
        "remove",
        "rerun",
        "run",
        "save",
        "send",
        "start",
        "stop",
        "update",
        "verify",
        "write",
    }
)


class Severity(str, Enum):
    WARN = "warn"
    ERROR = "error"


class Rule(str, Enum):
    UNIT = "unit"
    SECTION = "section"
    PROSE_SHARE = "prose-share"
    INLINE_LIST = "inline-list"
    LAYOUT = "layout"
    SENTENCE = "sentence"
    HOW_STEPS = "how-steps"
    SKILL_REFS = "skill-refs"
    SPEC = "spec"
    EVAL_CONTENT = "eval-content"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: Rule
    severity: Severity
    message: str


_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
_INLINE_CODE = re.compile(r"`[^`]*`")
_STRIP = (
    re.compile(r"`[^`]*`"),
    re.compile(r"\[([^\]]*)\]\([^)]*\)"),
    re.compile(r"https?://\S+"),
    re.compile(r"\b(e\.g|i\.e|etc|vs|cf|approx)\.", re.IGNORECASE),
    re.compile(r"\bv?\d+(\.\d+)+\b"),
    re.compile(r"(?<![\w./-])[\w./-]+\.[A-Za-z]{1,5}\b"),
)
_SENTENCE_END = re.compile(r"[.!?][)\"'*_]*(\s|$)")
_SERIES = re.compile(
    r"(?:[^,;:.!?()]+,\s*+){2,}[^,;:.!?()]*?\b(?:and|or)\b[^,;:.!?()]*"
)
_NESTED_JOIN = "\x1e;"
_LEAD_CONJUNCTION = re.compile(r"^\s*(and|or)\s+")


def _is_space(char: str) -> bool:
    return char.isspace() or "\x1c" <= char <= "\x1f"


def _strip(text: str) -> str:
    start, end = 0, len(text)
    while start < end and _is_space(text[start]):
        start += 1
    while end > start and _is_space(text[end - 1]):
        end -= 1
    return text[start:end]


def _word_count(text: str) -> int:
    in_word = False
    count = 0
    for char in text:
        if _is_space(char):
            in_word = False
        elif not in_word:
            count += 1
            in_word = True
    return count


def _plain(text: str) -> str:
    for pattern in _STRIP:
        text = pattern.sub(r"\1" if pattern.groups else "x", text)
    return text


def _sentences(text: str) -> int:
    return len(_SENTENCE_END.findall(_plain(text)))


def _longest_sentence_words(text: str) -> int:
    plain = _plain(text).replace(_NESTED_JOIN, ".")
    parts = _SENTENCE_END.sub("\n", plain).split("\n")
    return max(_word_count(part) for part in parts)


def _is_list_worthy(series: str) -> bool:
    items = [_word_count(_LEAD_CONJUNCTION.sub("", part)) for part in series.split(",")]
    return len(items) >= 4 or max(items[1:], default=0) >= 3


def _series_candidates(text: str):
    """Yield the comma series matched by Rust's inline-list scanner."""
    if text.count(",") < 2:
        return
    yield from (match.group() for match in _SERIES.finditer(text))


def _frontmatter_end(lines: list[str]) -> int:
    if not lines or _strip(lines[0]) != "---":
        return 0
    for index, line in enumerate(lines[1:], 1):
        if _strip(line) == "---":
            return index + 1
    return 0


def _is_fence(stripped: str) -> bool:
    return stripped.startswith(("```", "~~~"))


def _indent(line: str) -> int:
    for index, char in enumerate(line):
        if not _is_space(char):
            return index
    return len(line)


def _item_end(line: str) -> int | None:
    match = _ITEM.match(line)
    return match.end() if match else None


class _Scanner:
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.unit: list[str] = []
        self.unit_line = 0
        self.in_item = False
        self.item_indent = 0

    def push(self, rule: Rule, line: int, size: int) -> None:
        if rule is Rule.UNIT:
            warn_at, error_at, measure, label, hint = (
                UNIT_WARN,
                UNIT_ERROR,
                "sentences",
                "unit",
                "",
            )
        elif rule is Rule.INLINE_LIST:
            warn_at, error_at, measure, label, hint = (
                0,
                float("inf"),
                "items",
                "inline list",
                HINT_SERIES,
            )
        elif rule is Rule.SECTION:
            warn_at, error_at, measure, label, hint = (
                SECTION_WARN + 1,
                SECTION_ERROR + 1,
                "words",
                "section",
                "",
            )
        else:
            warn_at, error_at, measure, label, hint = (
                PROSE_WARN + 1,
                PROSE_ERROR + 1,
                "percent",
                "prose share",
                HINT_PROSE,
            )
        if size >= error_at:
            severity = Severity.ERROR
        elif size >= warn_at:
            severity = Severity.WARN
        else:
            return
        self.findings.append(
            Finding(
                self.path, line, rule, severity, f"({label}, {size} {measure}){hint}"
            )
        )

    def push_sentence(self, text: str) -> None:
        words = _longest_sentence_words(text)
        if words > SENTENCE_WARN:
            message = f"(sentence, {words} words)"
            self.findings.append(
                Finding(
                    self.path, self.unit_line, Rule.SENTENCE, Severity.WARN, message
                )
            )

    def close_unit(self) -> None:
        if self.unit:
            text = " ".join(self.unit)
            self.push(Rule.UNIT, self.unit_line, _sentences(text))
            self.push_sentence(text)
            plain = _INLINE_CODE.sub("x", text)
            series = next(
                (
                    candidate
                    for candidate in _series_candidates(plain)
                    if _is_list_worthy(candidate)
                ),
                None,
            )
            if series is not None:
                self.push(Rule.INLINE_LIST, self.unit_line, series.count(",") + 1)
        self.unit.clear()
        self.in_item = False
        self.item_indent = 0


def _scan(path: str, lines: list[str]) -> list[Finding]:
    first = _frontmatter_end(lines)
    scanner = _Scanner(path)
    fenced = False
    section_words, section_line = 0, first + 1
    prose_words = total_words = 0
    for number, line in enumerate(lines[first:], first + 1):
        stripped, indent = _strip(line), _indent(line)
        inside_item = scanner.in_item and indent > scanner.item_indent
        if _is_fence(stripped):
            fenced = not fenced
            if not inside_item:
                scanner.close_unit()
            continue
        if fenced or not stripped:
            continue
        words = _word_count(stripped)
        total_words += words
        if stripped.startswith("#"):
            scanner.close_unit()
            scanner.push(Rule.SECTION, section_line, section_words)
            section_words, section_line = 0, number
            continue
        if stripped.startswith(("|", "<!--")):
            if not inside_item:
                scanner.close_unit()
            continue
        section_words += words
        item = _item_end(line)
        if inside_item:
            nested = f"{_NESTED_JOIN} {line[item:]}" if item is not None else stripped
            scanner.unit.append(nested)
        elif item is not None:
            scanner.close_unit()
            scanner.unit.append(line[item:])
            scanner.unit_line, scanner.in_item, scanner.item_indent = (
                number,
                True,
                indent,
            )
        elif scanner.unit and not scanner.in_item:
            scanner.unit.append(stripped)
            prose_words += words
        else:
            scanner.close_unit()
            scanner.unit.append(stripped.lstrip("> "))
            scanner.unit_line = number
            prose_words += words
    scanner.close_unit()
    scanner.push(Rule.SECTION, section_line, section_words)
    if total_words >= PROSE_MIN_WORDS:
        scanner.push(Rule.PROSE_SHARE, first + 1, 100 * prose_words // total_words)
    return scanner.findings


def _layout(path: str, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    first = _frontmatter_end(lines)
    fenced = previous_item = False
    for number, line in enumerate(lines[first:], first + 1):
        stripped = _strip(line)
        if _is_fence(stripped):
            fenced, previous_item = not fenced, False
            continue
        if fenced or not stripped or stripped.startswith(("#", "|", "<!--", "---")):
            previous_item = False
            continue
        if stripped == "</content>":
            findings.append(
                Finding(
                    path, number, Rule.LAYOUT, Severity.WARN, "(stray </content> line)"
                )
            )
        item = _item_end(line) is not None
        indented = bool(line) and _is_space(line[0])
        if previous_item and not item and not indented:
            findings.append(
                Finding(
                    path,
                    number,
                    Rule.LAYOUT,
                    Severity.WARN,
                    "(lazy continuation; indent it under its item)",
                )
            )
        previous_item = item or (previous_item and indented)
    return findings


def _is_step_item(line: str) -> bool:
    match = _ITEM.match(line)
    if match is None:
        return False
    if match.group(2)[0].isdigit():
        return True
    first = line[match.end() :].lstrip("*_`").split(" ", 1)[0]
    return first.lower().rstrip(":*_`") in _IMPERATIVES


def _how_steps(path: str, lines: list[str]) -> list[Finding]:
    """Flag runs of numbered or imperative-opening list items at one indent."""
    if {"how", "evals"} & set(Path(path).parts):
        return []
    findings: list[Finding] = []
    run_indent, run_line, run_length = -1, 0, 0

    def close() -> None:
        if run_length >= HOW_RUN_MIN:
            message = f"({run_length} step-like items); outcome or how topic?"
            findings.append(
                Finding(path, run_line, Rule.HOW_STEPS, Severity.WARN, message)
            )

    fenced = False
    first = _frontmatter_end(lines)
    for number, line in enumerate(lines[first:], first + 1):
        stripped = _strip(line)
        if _is_fence(stripped):
            fenced = not fenced
            continue
        if fenced or not stripped:
            continue
        indent = _indent(line)
        if run_length and indent > run_indent:
            continue
        step = _is_step_item(line) and (run_length == 0 or indent == run_indent)
        if step and run_length:
            run_length += 1
            continue
        close()
        run_length = 1 if step else 0
        run_indent, run_line = indent, number
    close()
    return findings


_SKILL_TOKEN = re.compile(r"(?<![\w-])varde-[a-z][a-z0-9-]*")


def skill_refs(text: str, path: str, own: str, known: frozenset[str]) -> list[Finding]:
    """Flag prose and description lines that name another known skill."""
    if {"how", "evals"} & set(Path(path).parts) or own in ORCHESTRATING_SKILLS:
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    skip = {own} | ORCHESTRATING_SKILLS
    first = _frontmatter_end(lines)
    findings: list[Finding] = []
    fenced = False
    for number, line in enumerate(lines, 1):
        in_frontmatter = number <= first
        if in_frontmatter and not line.startswith("description:"):
            continue
        if _is_fence(_strip(line)):
            fenced = not fenced
            continue
        if fenced:
            continue
        names = sorted(
            {m for m in _SKILL_TOKEN.findall(line) if m in known and m not in skip}
        )
        if names:
            message = f"(names skill {', '.join(names)}; say what this skill does)"
            findings.append(
                Finding(path, number, Rule.SKILL_REFS, Severity.WARN, message)
            )
    return findings


SKILL_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
NAME_MAX, DESCRIPTION_MAX, COMPATIBILITY_MAX, SKILL_LINES_MAX = 64, 1024, 500, 500


def skill_spec(
    meta: object, directory: str, path: str, line_count: int
) -> list[Finding]:
    """Agent Skills spec limits for SKILL.md frontmatter and length."""
    if not isinstance(meta, dict):
        return [Finding(path, 1, Rule.SPEC, Severity.ERROR, "missing frontmatter")]
    problems: list[str] = []
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        problems.append("`name` must be a non-empty string")
    elif len(name) > NAME_MAX or not SKILL_NAME.fullmatch(name):
        problems.append(
            f"`name` {name!r} must be at most {NAME_MAX} chars of lowercase "
            "letters, digits, and single hyphens, not starting or ending with one"
        )
    elif name != directory:
        problems.append(f"`name` {name!r} must match its directory {directory!r}")
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        problems.append("`description` must be a non-empty string")
    elif len(description) > DESCRIPTION_MAX:
        problems.append(
            f"`description` is {len(description)} chars, max {DESCRIPTION_MAX}"
        )
    compatibility = meta.get("compatibility")
    if compatibility is not None and not (
        isinstance(compatibility, str) and 0 < len(compatibility) <= COMPATIBILITY_MAX
    ):
        problems.append(f"`compatibility` must be 1-{COMPATIBILITY_MAX} chars")
    findings = [Finding(path, 1, Rule.SPEC, Severity.ERROR, text) for text in problems]
    if line_count > SKILL_LINES_MAX:
        message = (
            f"SKILL.md has {line_count} lines; spec advises at most {SKILL_LINES_MAX}"
        )
        findings.append(Finding(path, 1, Rule.SPEC, Severity.WARN, message))
    return findings


# Detects assertions about skill text by phrasing. Subtle shapes are not detected
# and are left to the human read: a mode or rule named without a lead noun ("debug
# mode", "page rule S5"), and behavior-looking leads that really check text. The
# check is warn-only, so a miss costs a review comment and a false hit costs a note.
_CONTENT_LEADS = (
    "cites",
    "describes",
    "explains",
    "knows",
    "says that",
    "includes a section",
    "the rule applied",
)
_CONTENT_NOUN_LEADS = ("names", "mentions", "states", "lists")
_CONTENT_NOUNS = (
    "skill",
    "section",
    "heading",
    "reference",
    "topic",
    "mode",
    "rule",
    "owner",
    "phrase",
)
_CONTENT_TOKENS = ("references/", "contains the text")
_EVAL_SKILL_TOKEN = re.compile(
    r"(?<![/\w-])varde-[a-z][a-z-]*(?![a-z-])"
    r"(?!\s+(?:package|module|cli|binary|command|directory|dir)\b)"
)
_EVAL_ROUTES = re.compile(
    r"\broutes?\b.*\b(?:to|through)\b.*(?:\.md\b|\btopic\b|\bmode\b)"
)
_EVAL_LOADS = re.compile(
    r"(?<![-\w])(?:loads?|reads?|follows?)\b.*"
    r"(?:\bskill\b|\b(?!(?:readme|agents|claude|changelog)\b)[\w-]+\.md\b)"
)
_EVAL_MESSAGE = "(asserts skill content; assert what the agent does or produces)"


def _asserts_content(assertion: str) -> bool:
    text = assertion.lower().strip()
    lead_hit = text.startswith(_CONTENT_LEADS) or (
        text.startswith(_CONTENT_NOUN_LEADS)
        and any(noun in text for noun in _CONTENT_NOUNS)
    )
    return (
        lead_hit
        or any(token in text for token in _CONTENT_TOKENS)
        or bool(_EVAL_SKILL_TOKEN.search(text))
        or bool(_EVAL_ROUTES.search(text) or _EVAL_LOADS.search(text))
    )


def eval_content(text: str, path: str) -> list[Finding]:
    """Warn on eval assertions that check skill content, not agent behavior."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    cases = data.get("evals") if isinstance(data, dict) else None
    if not isinstance(cases, list):
        return []
    lines = text.splitlines()
    used: dict[str, int] = {}
    findings: list[Finding] = []
    for case in cases:
        assertions = case.get("assertions") if isinstance(case, dict) else None
        for assertion in assertions if isinstance(assertions, list) else []:
            if not isinstance(assertion, str) or not _asserts_content(assertion):
                continue
            quoted = json.dumps(assertion, ensure_ascii=False)
            rows = [n for n, row in enumerate(lines, 1) if quoted in row] or [1]
            seen = used.get(quoted, 0)
            used[quoted] = seen + 1
            line = rows[min(seen, len(rows) - 1)]
            findings.append(
                Finding(path, line, Rule.EVAL_CONTENT, Severity.WARN, _EVAL_MESSAGE)
            )
    return findings


def audit(text: str, path: str) -> list[Finding]:
    """Audit Markdown text and label findings with path."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return [*_scan(path, lines), *_layout(path, lines), *_how_steps(path, lines)]


def expand_skill_dir(directory: Path) -> list[Path]:
    """List SKILL.md followed by sorted Markdown references, without reading them."""
    found = [directory / "SKILL.md"] if (directory / "SKILL.md").is_file() else []
    references = directory / "references"
    if references.is_dir():
        found.extend(
            sorted(
                path
                for path in references.rglob("*")
                if path.is_file() and path.suffix == ".md"
            )
        )
    return found
