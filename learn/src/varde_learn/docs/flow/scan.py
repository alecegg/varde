"""Scan skill Markdown for internal pointers and external calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from varde_learn.docs.flow.model import EdgeKind, External, ExternalType, Runs

SPAN = re.compile(r"`([^`\n]+)`")
SECTION = re.compile(r"`#{1,6}\s+([^`]+)`")
PATH = re.compile(r"(?:^|[\s/(])((?:references|scripts|assets)/[^\s`)\]'\",;]+)")
SCRIPT = re.compile(r"(?:^|[\s/(])(scripts/[^\s`)\]'\",;]+)")
LINK = re.compile(r"\]\(([^)\s]+)[^)]*\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)")
NUMBERED = re.compile(r"^\d+[.)]?\s")
STEP = re.compile(r"^(\d+)[.)]\s+(.*)")
ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
LABEL = re.compile(
    r"^\s*[-*+]\s+(?:\*\*[^*]{1,60}\*\*|`[^`]{1,60}`:|[A-Za-z](?:[^:`*]|`[^`\n]*`){0,99}:(?:\s|$))"
)
END = re.compile(r"[.!?](?=\s)")
CLAUSE = re.compile(r"[.;!?](?=\s)")
CONDITION = re.compile(
    (  # noqa: UP034 - Explicit grouping is required for split regex text.
        r"(?i)\b(if|when|whenever|unless|otherwise|whether)\b|"
        r"\bonly (?:as|for|after|during|in|on)\b|→|->"
    )
)
CASE = re.compile(
    r"(?i)\b(unmerged|separate|isolated|standalone|fallback|failure|failed|stale)\b"
)
HANDOFF = re.compile(
    (  # noqa: UP034 - Explicit grouping is required for split regex text.
        r"(?i)\bthen (?:continue|proceed|return|go|move|hand)|"
        r"\bcontinue (?:with|per|in|at|to)\b|\bnext:|"
        r"\bhand(?:s|ed)? (?:it )?off\b|\brecommend|"
        r"\bresume (?:a|an|it|planning|work)\b|\binstead\b(?!\s+of)"
    )
)
LOAD = re.compile(
    r"(?i)\b(read|reads|load|loads|loaded|follow|follows|apply|applies|run|runs|see|use|uses|open|opens|per)\b|→|->"
)
MODE = re.compile(r"^(varde-[a-z][a-z0-9-]*)\s+([a-z][a-z0-9_-]*)(?:\s.*)?$")
SKILL_NAME = re.compile(r"^varde-[a-z][a-z0-9-]*$")
MODE_WORD = re.compile(r"^\s+([a-z][a-z0-9_-]*)\b")
DISPATCH = re.compile(
    (  # noqa: UP034 - Explicit grouping is required for split regex text.
        r"(?i)\b(?:dispatch|delegat|spawn|launch)\w*|"
        r"\bbrief(?:s|ed)? (?:the|an?|each)\b|\bgive an agent\b"
    )
)
AGENT = re.compile(
    r"(?i)\b(builder|reviewer|review agent|independent agent|an agent)s?\b"
)
EDITS = re.compile(r"(?i)\bbefore (?:\w+ )?(?:edit|edits|editing|changes)\b")
ROLE = re.compile(
    (  # noqa: UP034 - Explicit grouping is required for split regex text.
        r"(?i)^\W*(?:\d+[.)]\s*)?(?:the|a|an|each)?\s*"
        r"(?:gate\s+)?(?:reviewer|builder)s?\b|"
        r"\bas an? (?:independent |gate )?reviewer\b|"
        r"\b(?:reviewer|builder)s? (?:follows|loads|reads)\b"
    )
)
ROLE_HEADING = re.compile(
    r"(?i)^(?:the |as (?:an? |the )?)?(?:gate )?(?:builder|reviewer)s?\b"
)
OPENING = re.compile(
    r"(?i)^\W*(?:\d+[.)]\s*)?(?:with|without|for|on|after) (?:a|an|each|no|any)\b"
)
REVIEWED = re.compile(r"(?i)\b(independent|reviewer)\b")
RUNS = re.compile(r"(?i)\bfor\s*$")
ROUTE_WORD = re.compile(r"(?i)\b(?:route|section)\b")
QUALIFIER_WORD = re.compile(r"(?i)[a-z0-9]+(?:-[a-z0-9]+)*")
SCHEME = re.compile(r"^[A-Za-z][\w+.-]*:")
ENTRY_ROUTING = "Entry routing"
STOP_WORDS = {
    "and",
    "but",
    "or",
    "then",
    "to",
    "for",
    "with",
    "from",
    "before",
    "after",
    "when",
    "while",
    "unless",
    "because",
    "route",
}
IGNORED_QUALIFIERS = {
    "and",
    "follow",
    "its",
    "the",
    "a",
    "an",
    "via",
    "through",
    "using",
    "use",
}
KIND_MARKER = "<!-- kind: reference -->"


def matches(pattern: re.Pattern[str], text: str) -> bool:
    return pattern.search(text) is not None


def find_all(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    return list(pattern.finditer(text))


def floor_boundary(text: str, index: int) -> int:
    return max(0, min(index, len(text)))


def slice_text(text: str, start: int, stop: int) -> str:
    start, stop = floor_boundary(text, start), floor_boundary(text, stop)
    return text[start:stop] if start < stop else ""


def sentence_end(text: str, pos: int, end: re.Pattern[str]) -> int:
    found = end.search(text, floor_boundary(text, pos))
    return found.end() if found else len(text)


def bounds(text: str, pos: int, end: re.Pattern[str]) -> tuple[int, int]:
    prior = list(end.finditer(text[: floor_boundary(text, pos)]))
    return (prior[-1].end() if prior else 0, sentence_end(text, pos, end))


def sentence_at(text: str, pos: int, end: re.Pattern[str]) -> str:
    start, stop = bounds(text, pos, end)
    return slice_text(text, start, stop)


def short_to(text: str, limit: int) -> str:
    text = text.replace("`", "").replace("**", "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def short(text: str) -> str:
    return short_to(text, 60)


def plain(text: str) -> str:
    return SPAN.sub(lambda m: " " * len(m[0]), text)


def read_text(path: Path) -> str:
    try:
        return (
            path.read_bytes()
            .decode("utf-8", errors="replace")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
    except OSError:
        return ""


def text_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def tokens(path: Path) -> int:
    return text_tokens(read_text(path))


def is_reference(path: Path) -> bool:
    return read_text(path).split("\n", 1)[0] == KIND_MARKER


def file_name(path: Path) -> str:
    return path.name


def read_manifest(path: Path) -> dict[str, set[str]]:
    manifest = {}
    for line in read_text(path).splitlines():
        parts = line.split()
        if parts:
            manifest[parts[0]] = set(parts[1:])
    return manifest


@dataclass
class SkillDir:
    dir: Path
    name: str = field(init=False)
    manifest: dict[str, set[str]] = field(init=False)

    def __post_init__(self) -> None:
        self.name = self.dir.name
        self._shared = self.dir.parent / "shared"
        manifest = self._shared / "MANIFEST"
        if not manifest.is_file():
            root = next(
                (
                    parent
                    for parent in (self.dir, *self.dir.parents)
                    if (parent / ".git").exists()
                ),
                None,
            )
            if root is not None:
                manifests = sorted(root.glob("**/src/*/skills/shared/MANIFEST"))
                manifest = next(
                    (
                        path
                        for path in manifests
                        if any(
                            self.name in skills
                            for skills in read_manifest(path).values()
                        )
                    ),
                    manifest,
                )
                if manifest.is_file():
                    self._shared = manifest.parent
        self.manifest = read_manifest(manifest)

    def shared_dir(self) -> Path:
        return self._shared

    def shared_files(self, files: list[str]) -> list[str]:
        return sorted(
            rel
            for rel, skills in self.manifest.items()
            if self.name in skills and rel not in files
        )

    def actual_path(self, rel: str) -> Path:
        local = self.dir / rel
        if not local.is_file() and self.name in self.manifest.get(rel, set()):
            return self.shared_dir() / rel
        return local

    def read(self, rel: str) -> str:
        return read_text(self.actual_path(rel))


def normpath(path: str) -> str:
    absolute = path.startswith("/")
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        elif part == ".." and absolute:
            continue
        else:
            parts.append(part)
    joined = "/".join(parts)
    return f"/{joined}" if absolute else joined or "."


@dataclass
class Target:
    raw: str
    is_link: bool
    col: int


def path_target(match: re.Match[str], base: int) -> Target:
    return Target(match[1], False, base + match.start(1))


def targets(line: str, fenced: bool) -> list[Target]:
    found: list[Target] = []
    if fenced:
        return [path_target(m, 0) for m in find_all(SCRIPT, line)]
    spans = [(m[1], m.start(1)) for m in find_all(SPAN, line)]
    if line.count("`") % 2:
        cut = line.rfind("`") + 1
        spans.append((line[cut:], cut))
    for span, start in spans:
        found.extend(path_target(m, start) for m in find_all(PATH, span))
    for match in find_all(LINK, plain(line)):
        text = match[1]
        if not text.startswith(("#", "/", "<")) and not matches(SCHEME, text):
            found.append(Target(text, True, match.start(1)))
    return found


def resolve(
    directory: SkillDir, source: str, raw: str, is_link: bool
) -> tuple[str | None, bool]:
    target = raw.split("#", 1)[0].rstrip(".:")
    if not target or target.endswith("/") or any(ch in target for ch in "<>*{}$"):
        return None, True
    folders = source.split("/")[:-1]
    depths = [len(folders)] if is_link else list(range(len(folders), -1, -1))
    first = None
    for depth in depths:
        rel = normpath(f"{'/'.join(folders[:depth])}/{target}" if depth else target)
        if rel.startswith(".."):
            continue
        if directory.actual_path(rel).is_file():
            return rel, False
        if first is None:
            first = rel
    return first, first is None


@dataclass
class BlockLine:
    n: int
    text: str
    step: str | None


@dataclass
class Block:
    lines: list[BlockLine]
    heading: str
    case: bool
    role: bool
    table: bool
    fenced: bool


@dataclass
class Head:
    level: int
    case: bool
    role: bool


def numbered_levels(lines: list[str]) -> set[int]:
    numbered = set()
    for line in lines:
        match = HEADING.match(line.strip())
        if match and len(match[1]) > 1 and matches(NUMBERED, match[2]):
            numbered.add(len(match[1]))
    return numbered


def heading_is_case(level: int, text: str, numbered: set[int]) -> bool:
    return level > 1 and (
        matches(CONDITION, plain(text))
        or matches(CASE, text)
        or (level in numbered and not matches(NUMBERED, text))
    )


def blocks(lines: list[str]) -> list[Block]:
    numbered = numbered_levels(lines)
    out: list[Block] = []
    heads: list[Head] = []
    heading, step, fenced, current = "(top)", None, False, None
    for index, line in enumerate(lines):
        n, stripped = index + 1, line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced, current = not fenced, None
            continue
        case, role = any(head.case for head in heads), any(head.role for head in heads)
        if fenced:
            out.append(
                Block([BlockLine(n, line, step)], heading, case, role, False, True)
            )
            continue
        heading_match = HEADING.match(stripped)
        if heading_match:
            level, title = len(heading_match[1]), heading_match[2]
            heads = [head for head in heads if head.level < level]
            heads.append(
                Head(
                    level,
                    heading_is_case(level, title, numbered),
                    matches(ROLE_HEADING, title),
                )
            )
            heading, step, current = short(title), None, None
            continue
        table = stripped.startswith("|")
        if not stripped or table or matches(ITEM, line):
            current = None
        step_match = STEP.match(line)
        if step_match:
            step = f"{heading} / step {step_match[1]}: {short_to(step_match[2], 40)}"
        elif stripped and not line[0].isspace() and not table:
            step = None
        if not stripped:
            continue
        if current is None:
            out.append(Block([], heading, case, role, table, False))
            current = len(out) - 1
        out[current].lines.append(BlockLine(n, line, step))
        if table:
            current = None
    return out


@dataclass
class Pointer:
    to: str
    raw: str
    context: str
    conditional: bool
    kind: EdgeKind
    table: bool
    line: int


@dataclass
class Scanned:
    section: str
    edits: bool
    body: Pointer | External


@dataclass
class Draft:
    span: tuple[int, int]
    external: External
    edits: bool


def new_external(kind: ExternalType, target: str, context: str, line: int) -> External:
    return External(
        "", kind, target, "", "", None, context, False, EdgeKind.MENTION, False, line
    )


def first_nonempty(row: str | None, step: str | None, heading: str) -> str:
    return next((value for value in (row, step) if value), heading)


class BlockScan:
    def __init__(self, source: str, block: Block):
        self.source, self.block = source, block
        text, starts = "", []
        for line in block.lines:
            stripped = line.text.strip()
            indent = len(line.text) - len(line.text.lstrip())
            starts.append(len(text) - indent)
            text += stripped + " "
        self.text = text
        self.flat, self.bare = plain(text), text.replace("`", " ")
        self.starts = starts
        self.labeled = matches(LABEL, text)
        first = block.lines[0].text.strip() if block.lines else ""
        self.row = short(first.strip("|").split("|")[0]) if block.table else None

    def position(self, offset: int, col: int) -> int:
        return max(0, offset + col)

    def context(self, step: str | None) -> str:
        return first_nonempty(self.row, step, self.block.heading)

    def classify(self, pos: int) -> tuple[EdgeKind, bool]:
        block, skill_md = self.block, self.source == "SKILL.md"
        clause = sentence_at(self.flat, pos, CLAUSE)
        if block.table and not skill_md and matches(HANDOFF, clause):
            return EdgeKind.HANDOFF, True
        if block.fenced or block.table:
            return EdgeKind.LOAD, block.table and not skill_md
        sentence = sentence_at(self.flat, pos, END)
        if skill_md and block.heading == ENTRY_ROUTING:
            kind = EdgeKind.HANDOFF
        elif block.role or matches(ROLE, sentence) or matches(ROLE, clause):
            kind = EdgeKind.ROLE
        elif matches(HANDOFF, clause):
            kind = EdgeKind.HANDOFF
        elif matches(LOAD, sentence):
            kind = EdgeKind.LOAD
        else:
            kind = EdgeKind.MENTION
        upto = slice_text(self.flat, 0, sentence_end(self.flat, pos, CLAUSE))
        conditional = (
            block.case
            or self.labeled
            or matches(OPENING, sentence)
            or matches(CONDITION, upto)
        )
        return kind, conditional

    def edits(self, pos: int) -> bool:
        return not self.block.fenced and matches(
            EDITS, sentence_at(self.flat, pos, END)
        )

    def find_dispatches(self) -> list[Draft]:
        drafts = []
        for match in find_all(AGENT, self.bare):
            start, stop = bounds(self.bare, match.start(), END)
            span = (start, stop)
            if any(d.span == span for d in drafts) or not matches(
                DISPATCH, slice_text(self.bare, start, stop)
            ):
                continue
            at = max(
                (i for i, value in enumerate(self.starts) if value <= match.start()),
                default=0,
            )
            line = self.block.lines[at]
            target = "builder" if match[1].lower() == "builder" else "review"
            external = new_external(
                ExternalType.AGENT, target, self.context(line.step), line.n
            )
            external = replace(
                external,
                conditional=self.classify(match.start())[1],
                table=self.block.table,
            )
            drafts.append(Draft(span, external, self.edits(match.start())))
        return drafts


def dispatch_at(drafts: list[Draft], pos: int) -> int | None:
    return next(
        (i for i, draft in enumerate(drafts) if draft.span[0] <= pos < draft.span[1]),
        None,
    )


def scan(directory: SkillDir, source: str, skill_names: set[str]) -> list[Scanned]:
    return [
        result
        for block in blocks(directory.read(source).split("\n"))
        for result in scan_block(directory, source, skill_names, block)
    ]


def scan_block(
    directory: SkillDir, source: str, skill_names: set[str], block: Block
) -> list[Scanned]:
    state = BlockScan(source, block)
    drafts = [] if block.fenced else state.find_dispatches()
    out = []
    for line, offset in zip(block.lines, state.starts, strict=False):
        context = state.context(line.step)
        for target in targets(line.text, block.fenced):
            rel, skip = resolve(directory, source, target.raw, target.is_link)
            if rel is None or skip or rel == source:
                continue
            pos = state.position(offset, target.col)
            owner = dispatch_at(drafts, pos)
            if (
                owner is not None
                and drafts[owner].external.runs is None
                and matches(RUNS, slice_text(state.text, 0, pos - 1))
            ):
                drafts[owner].external = replace(
                    drafts[owner].external, runs=Runs(file=rel)
                )
            kind, conditional = state.classify(pos)
            out.append(
                Scanned(
                    block.heading,
                    state.edits(pos),
                    Pointer(
                        rel, target.raw, context, conditional, kind, block.table, line.n
                    ),
                )
            )
        if not block.fenced:
            scan_skill_calls(state, skill_names, line, offset, context, drafts, out)
    out.extend(Scanned(block.heading, draft.edits, draft.external) for draft in drafts)
    return out


@dataclass
class SkillCall:
    skill: str
    mode: str
    mode_end: int


def skill_call(line: str, span: re.Match[str], offset: int) -> SkillCall | None:
    content = span[1]
    base = offset + span.start(1)
    call = MODE.match(content)
    if call:
        return SkillCall(call[1], call[2], max(0, base + call.end(2)))
    if not matches(SKILL_NAME, content):
        return None
    following = MODE_WORD.match(line[span.end() :])
    if not following or following[1] in STOP_WORDS:
        return None
    return SkillCall(
        content, following[1], max(0, offset + span.end() + following.end(1))
    )


def qualifier_of(tail: str) -> str | None:
    route_word = ROUTE_WORD.search(tail)
    if not route_word:
        return None
    words = [
        m[0].lower()
        for m in find_all(QUALIFIER_WORD, tail[: route_word.start()])
        if m[0].lower() not in IGNORED_QUALIFIERS
    ]
    return " ".join(words) or None


def scan_skill_calls(
    state: BlockScan,
    skill_names: set[str],
    line: BlockLine,
    offset: int,
    context: str,
    drafts: list[Draft],
    out: list[Scanned],
) -> None:
    for span in find_all(SPAN, line.text):
        call = skill_call(line.text, span, offset)
        if call is None or (skill_names and call.skill not in skill_names):
            continue
        pos = state.position(offset, span.start())
        owner = dispatch_at(drafts, pos)
        if owner is None and call.mode == "report" and matches(REVIEWED, state.flat):
            owner = add_report_review(state, line, context, pos, drafts)
        if owner is not None:
            external = drafts[owner].external
            if external.runs is None:
                drafts[owner].external = replace(
                    external, runs=Runs(skill=call.skill, mode=call.mode)
                )
            continue
        out.append(skill_item(state, call, line, context, pos))


def add_report_review(
    state: BlockScan, line: BlockLine, context: str, pos: int, drafts: list[Draft]
) -> int:
    external = new_external(ExternalType.AGENT, "review", context, line.n)
    external = replace(
        external,
        table=state.block.table,
        conditional=state.classify(pos)[1],
        report_order=True,
    )
    span = (-line.n, -line.n)
    draft = Draft(span, external, state.edits(pos))
    existing = next((i for i, item in enumerate(drafts) if item.span == span), None)
    if existing is not None:
        drafts[existing] = draft
        return existing
    drafts.append(draft)
    return len(drafts) - 1


def skill_item(
    state: BlockScan, call: SkillCall, line: BlockLine, context: str, pos: int
) -> Scanned:
    kind, conditional = state.classify(pos)
    _, stop = bounds(state.flat, pos, END)
    tail = slice_text(state.flat, call.mode_end, stop)
    external = new_external(
        ExternalType.SKILL, f"{call.skill} {call.mode}", context, line.n
    )
    external = replace(
        external,
        skill=call.skill,
        mode=call.mode,
        conditional=conditional,
        kind=kind,
        table=state.block.table,
        qualifier=qualifier_of(tail),
    )
    return Scanned(state.block.heading, state.edits(pos), external)
