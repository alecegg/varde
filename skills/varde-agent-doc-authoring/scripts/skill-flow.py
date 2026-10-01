#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Map how a skill loads its files (criteria.md, Loading and references).

Usage: skill-flow.py [--mermaid|--json|--write|--check] <skill-dir>...

An edge is a pointer from a Markdown file to another file of the same skill:
a references/, scripts/ or assets/ path inside backticks, or a relative
Markdown link. Fenced code is skipped except for scripts/ paths. Each edge is
labeled with its table row's first cell, else its numbered step, else its
nearest heading. Sizes are estimated tokens of the whole file, one per four
characters (a deterministic offline estimate; exact counts need the target
model's tokenizer). Sizes cover Markdown files only; scripts and other
non-Markdown files show no size and add to no cost, because agents run them.

Rules are text heuristics over one paragraph or list item (a block), its
sentence (text up to . ! or ?) and its clause (also ending at ;). Backticked
spans are ignored when matching words.
  kind          a table row outside SKILL.md with a hand-off phrase (below):
                handoff. Else table row, or fenced script path: load. Else role: the
                block sits under a role heading (Executor, The reviewer, As
                a gate reviewer) or the sentence or clause has a role
                subject ("The reviewer ...", "a gate reviewer follows"); a
                role load belongs to the subagent and is out of the main
                agent's cost. Else a hand-off phrase in the clause (then
                continue/proceed/return/go/move, continue with/per/in/at/to,
                next:, hand off, recommend, resume a/an/it/planning/work):
                handoff. Else a load word in the sentence (read, load,
                follow, apply, run, see, use, open, per, an arrow): load.
                Else: mention.
  conditional   a load in a table row outside SKILL.md; or a condition word
                (if, when, whenever, unless, otherwise, whether, only
                as/for/after/during/in/on, an arrow) in the block up to the
                end of its clause; or a sentence opening with with/without/
                for/on/after + a/an/each/no/any; or a bullet that starts
                with a label (**Label**, `label`:, or Label: within 100
                characters, backticks allowed); or a governing heading that
                is a case: it has a condition word or a state word
                (unmerged, separate, isolated, standalone, fallback,
                failure, failed, stale), or it is unnumbered where sibling
                headings are numbered ("## 1. ..."). Subheadings inherit it.
  route         a SKILL.md table row, plus any SKILL.md section the row
                names as a backticked heading (`## Name`). Other SKILL.md
                loads outside tables (the preamble, gotchas) are global:
                every route reaches them. A global load whose sentence says
                "before [implementation] edits/editing/changes" is an edit
                gate: only routes that edit need it, so it counts in max,
                not min. Without any SKILL.md table row, each label is a
                route. Max follows every load edge transitively; min follows
                only unconditional ones and the route's own table cells.
                Both include SKILL.md and count only this skill (min_tokens,
                max_tokens). Hand-offs, mentions and role loads are in
                neither; a route lists the hand-off targets it reaches.
  inline mode   a load-classified backticked `varde-<skill> <mode>` span, or
                a backticked skill followed by an unquoted mode, outside a
                dispatch sentence. Suggested and cited spans stay mentions.
                The skill is a sibling skill directory (or any such span when
                the skill has no siblings; other varde-* names are CLI
                commands and skipped). A same-sentence `<qualifier> route` or
                `<qualifier> section` selects routes whose entry stem or label
                contains all qualifier words, preferring the route with fewest
                entry files; no match is unresolved. Without one, the mode
                resolves by entry file stem (fewest entry files), then the
                first route label containing the word; no match is unresolved.
                Main min/max
                (main_min_tokens, main_max_tokens) are the route's files plus
                every inline route reached from its min or max files,
                transitively, each (skill, file) counted once, never
                re-entering a route already on the path. Under a SKILL.md
                heading named Entry routing, a load or inline mode is a
                hand-off instead: it adds nothing and joins the route's
                hand-off list.
  dispatch      a sentence with a dispatch word (dispatch, delegate, spawn,
                launch, brief the/a/each, give an agent) and an agent word
                (executor, reviewer, review agent, independent agent, an
                agent); or a `varde-<skill> report` span in a block that
                says independent or reviewer. An executor word dispatches
                agents/varde-executor; the others dispatch agents/varde-reviewer. The
                agent runs, in order: the sentence's mode span; a pointer
                after "for"; else an executor runs the varde-change route
                whose label says executor, and a reviewer runs the gate:
                review-gate-record.md and review-gates.md of the dispatching
                skill plus loads reached from the record. Per-dispatch cost
                is the definition agents/varde-<role>/claude.md (from the skills
                directory's parent, when present), the SKILL.md of each
                skill in its skills: frontmatter, and the run's files, each
                once. A dispatch is conditional unless the route's min files
                reach it. Costs are per dispatch; the text cannot know how
                many tasks or rounds run.
Limits: words only approximate meaning. A label bullet that is a note, a
"per" or arrow that is not a load, a load verb outside these words ("build
the folder with"), a condition the text states outside these words, or a
case heading without them is misread. Min is literal: a step the text makes
conditional ("unless completion was deferred", "when interactive") stays
out of min even when real runs always take it. A `varde-x` span followed by
an unquoted mode ("run `varde-change` build") is missed, and a mode with no
matching entry stem or label word (varde-change build) is unresolved. A name
that is both a skill and a CLI (varde-toz) resolves as a skill. Loads inside
a dispatched agent's own dispatches are not added. Max is an upper bound
that follows every conditional branch. Mentions and role loads are not drawn
in the chart.

Findings, for files under references/, scripts/ and assets/:
  chain         a reference whose only caller is another reference with an
                unconditional load edge to it
  single caller a reference loaded or handed off to from one place
  shared        a reference loaded or handed off to from two or more places
  unreferenced  a file nothing points to, not even a mention
  missing       a pointer to a file that does not exist
  cycle         a defect: two files that link to each other
  fan-out       a warning: a file with 6 or more links out
  density       a warning: more than 2 links out per linking file on average
Structure counts links: distinct (from, to) load and hand-off edges between
files, SKILL.md excluded as a source; mentions, role loads, inline modes and
dispatches are not links. It reports mutual links, the file with the most
links out, and links per file that has any. Findings never change the exit.
A place is a calling file; in SKILL.md each route is its own place.
Default output is a text report; --mermaid prints a flowchart TD per skill;
--json prints the same data. --write saves each skill's FLOW.md (chart, routes,
findings) for human readers; --check exits 1 when a FLOW.md is stale. Exits 1
on missing targets, 2 on bad input.
"""
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

DIRS = ("references", "scripts", "assets")
SPAN = re.compile(r"`([^`\n]+)`")
SECTION = re.compile(r"`#{1,6}\s+([^`]+)`")
PATH = re.compile(r"(?:^|(?<=[\s/(]))((?:references|scripts|assets)/[^\s`)\]'\",;]+)")
SCRIPT = re.compile(r"(?:^|(?<=[\s/(]))(scripts/[^\s`)\]'\",;]+)")
LINK = re.compile(r"\]\(([^)\s]+)[^)]*\)")
HEADING = re.compile(r"(#{1,6})\s+(.*)")
NUMBERED = re.compile(r"\d+[.)]?\s")
STEP = re.compile(r"(\d+)[.)]\s+(.*)")
ITEM = re.compile(r"\s*([-*+]|\d+[.)])\s+")
LABEL = re.compile(r"\s*[-*+]\s+(?:\*\*[^*]{1,60}\*\*|`[^`]{1,60}`:"
                   r"|[A-Za-z](?:[^:`*]|`[^`\n]*`){0,99}:(?:\s|$))")
END = re.compile(r"[.!?](?=\s)")
CLAUSE = re.compile(r"[.;!?](?=\s)")
CONDITION = re.compile(r"\b(if|when|whenever|unless|otherwise|whether)\b|\bonly (?:as|for|after|during|in|on)\b"
                       r"|→|->", re.I)
CASE = re.compile(r"\b(unmerged|separate|isolated|standalone|fallback|failure|failed|stale)\b", re.I)
HANDOFF = re.compile(
    r"\bthen (?:continue|proceed|return|go|move|hand)|\bcontinue (?:with|per|in|at|to)\b"
    r"|\bnext:|\bhand(?:s|ed)? (?:it )?off\b|\brecommend|\bresume (?:a|an|it|planning|work)\b"
    r"|\binstead\b(?!\s+of)",
    re.I)
LOAD = re.compile(r"\b(read|reads|load|loads|loaded|follow|follows|apply|applies|run|runs"
                  r"|see|use|uses|open|opens|per)\b|→|->", re.I)
MODE = re.compile(r"(varde-[a-z][a-z0-9-]*)\s+([a-z][a-z0-9_-]*)(?:\s.*)?")
DISPATCH = re.compile(r"\b(?:dispatch|delegat|spawn|launch)\w*|\bbrief(?:s|ed)? (?:the|an?|each)\b"
                      r"|\bgive an agent\b", re.I)
AGENT = re.compile(r"\b(executor|reviewer|review agent|independent agent|an agent)s?\b", re.I)
EDITS = re.compile(r"\bbefore (?:\w+ )?(?:edit|edits|editing|changes)\b", re.I)
ROLE = re.compile(r"^\W*(?:\d+[.)]\s*)?(?:the|a|an|each)?\s*(?:gate\s+)?(?:reviewer|executor)s?\b"
                  r"|\bas an? (?:independent |gate )?reviewer\b"
                  r"|\b(?:reviewer|executor)s? (?:follows|loads|reads)\b", re.I)
ROLE_HEADING = re.compile(r"(?:the |as (?:an? |the )?)?(?:gate )?(?:executor|reviewer)s?\b", re.I)
OPENING = re.compile(r"\W*(?:\d+[.)]\s*)?(?:with|without|for|on|after) (?:a|an|each|no|any)\b", re.I)
REVIEWED = re.compile(r"\b(independent|reviewer)\b", re.I)
RUNS = re.compile(r"\bfor\s*$", re.I)  # "dispatch one executor for `references/x.md`"
SKIP = re.compile(r"\bskips?\b", re.I)  # a route-scoped skip directive
AGENT_DIRS = {"executor": "varde-executor", "review": "varde-reviewer"}  # dispatch label -> agents/ folder
EXECUTOR = ("varde-change", "executor")  # the executor runs this skill's route with this word
FAN_OUT, DENSITY = 6, 2  # structure warnings: links out of one file, average links
CYCLOMATIC_WARN = 10  # structure warning: a route's cyclomatic complexity
COGNITIVE_WARN, COGNITIVE_ERROR = 10, 15  # structure warning/error: cognitive complexity
ROUTE_FILES_WARN = 15  # structure warning: files reached by one route
DIAGRAM_EDGES_WARN = 60  # structure warning: total edges in the skill's diagram
STRUCTURE = ("cycle:", "fan-out:", "density:")
GATE = ("references/review-gate-record.md", "references/review-gates.md")  # a gate reviewer
ENTRY_ROUTING = "Entry routing"  # a SKILL.md heading whose loads and inline modes hand off


def module_of(path):
    """A file's module: scripts/assets by directory, else the text before its first hyphen."""
    top = path.split("/", 1)[0]
    if top in ("scripts", "assets"):
        return top
    return Path(path.split("/")[-1]).stem.split("-", 1)[0]


def tokens(path):
    try:
        return -(-len(path.read_text(errors="replace")) // 4)
    except OSError:
        return 0


KIND_MARKER = "<!-- kind: reference -->"


def file_kind(path):
    """'reference' when the file's line 1 is exactly the kind marker, else 'procedure'."""
    try:
        with path.open(errors="replace") as fh:
            first = fh.readline().rstrip("\n")
    except OSError:
        return "procedure"
    return "reference" if first == KIND_MARKER else "procedure"


@lru_cache(maxsize=None)
def shared_manifest(shared_dir):
    """Parse <skill>/../shared/MANIFEST once: relative path -> skills listing it."""
    manifest = {}
    try:
        for line in (shared_dir / "MANIFEST").read_text().splitlines():
            parts = line.split()
            if parts:
                manifest[parts[0]] = set(parts[1:])
    except OSError:
        pass
    return manifest


def actual_path(skill, rel):
    """The file rel points to: in-skill, else the shared copy this skill lists."""
    local = skill / rel
    if local.is_file():
        return local
    shared_dir = skill.parent / "shared"
    if skill.name in shared_manifest(shared_dir).get(rel, ()):
        return shared_dir / rel
    return local


def short(text, limit=60):
    text = re.sub(r"`|\*\*", "", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def plain(text):
    """Blank out backticked spans, keeping offsets."""
    return SPAN.sub(lambda m: " " * len(m.group(0)), text)


def targets(line, fenced):
    """Yield (raw target, is_link, column) for every pointer on one line."""
    if fenced:
        for match in SCRIPT.finditer(line):
            yield match.group(1), False, match.start(1)
        return
    spans = [(m.group(1), m.start(1)) for m in SPAN.finditer(line)]
    if line.count("`") % 2:
        cut = line.rfind("`") + 1
        spans.append((line[cut:], cut))  # a span that wraps to the next line
    for span, start in spans:
        for match in PATH.finditer(span):
            yield match.group(1), False, start + match.start(1)
    for match in LINK.finditer(plain(line)):
        link = match.group(1)
        if not link.startswith(("#", "/", "<")) and not re.match(r"[A-Za-z][\w+.-]*:", link):
            yield link, True, match.start(1)


def resolve(skill, source, raw, is_link):
    """Return (skill-relative path or None, skip). Skip placeholders and dirs."""
    target = raw.split("#", 1)[0].rstrip(".:")
    if not target or target.endswith("/") or re.search(r"[<>*{}$]", target):
        return None, True
    parts = Path(source).parts[:-1]
    bases = [parts] if is_link else [parts[:i] for i in range(len(parts), -1, -1)]
    first = None
    for base in bases:
        rel = os.path.normpath(os.path.join(*base, target)) if base else os.path.normpath(target)
        if rel.startswith(".."):
            continue
        first = first or rel
        if actual_path(skill, rel).is_file():
            return rel, False
    return first, first is None


def blocks(lines):
    """Group lines into paragraphs, list items, table rows and fenced lines."""
    numbered = set()
    for line in lines:
        match = HEADING.match(line.strip())
        if match and len(match.group(1)) > 1 and NUMBERED.match(match.group(2)):
            numbered.add(len(match.group(1)))
    out, heads, heading, step, fenced, current = [], [], "(top)", None, False, None
    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced, current = not fenced, None
            continue
        case = any(h[1] for h in heads)
        role = any(h[2] for h in heads)
        if fenced:
            out.append({"lines": [(n, line, step)], "heading": heading, "case": case,
                        "role": role,
                        "table": False, "fenced": True})
            continue
        match = HEADING.match(stripped)
        if match:
            level, text = len(match.group(1)), match.group(2)
            is_case = level > 1 and bool(
                CONDITION.search(plain(text)) or CASE.search(text)
                or (level in numbered and not NUMBERED.match(text)))
            is_role = bool(ROLE_HEADING.match(text))
            heads = [h for h in heads if h[0] < level] + [(level, is_case, is_role)]
            heading, step, current = short(text), None, None
            continue
        table = stripped.startswith("|")
        if not stripped or table or ITEM.match(line):
            current = None
        match = STEP.match(line)
        if match:
            step = f"{heading} / step {match.group(1)}: {short(match.group(2), 40)}"
        elif stripped and not line[0].isspace() and not table:
            step = None
        if not stripped:
            continue
        if current is None:
            current = {"lines": [], "heading": heading, "case": case, "role": role,
                       "table": table,
                       "fenced": False}
            out.append(current)
        current["lines"].append((n, line, step))
        if table:
            current = None
    return out


def sentence_end(text, pos, end=END):
    match = end.search(text, pos)
    return match.start() + 1 if match else len(text)


def bounds(text, pos, end=END):
    start = max((m.end() for m in end.finditer(text, 0, pos)), default=0)
    return start, sentence_end(text, pos, end)


def sentence(text, pos, end=END):
    start, stop = bounds(text, pos, end)
    return text[start:stop]


def scan(skill, source, skill_names):
    """Yield internal pointers and external calls for one Markdown file."""
    lines = actual_path(skill, source).read_text(errors="replace").split("\n")
    for block in blocks(lines):
        text, starts = "", []
        for _, line, _ in block["lines"]:
            starts.append(len(text) - (len(line) - len(line.lstrip())))
            text += line.strip() + " "
        flat = plain(text)
        labeled = bool(LABEL.match(text))
        first = block["lines"][0][1].strip()
        row = short(first.strip("|").split("|")[0]) if block["table"] else None

        def classify(pos):
            if block["table"] and source != "SKILL.md" \
                    and HANDOFF.search(sentence(flat, pos, CLAUSE)):
                return "handoff", True
            if block["fenced"] or block["table"]:
                return "load", block["table"] and source != "SKILL.md"
            if source == "SKILL.md" and block["heading"] == ENTRY_ROUTING:
                kind = "handoff"  # the request leaves this skill; adds nothing
            elif block["role"] or ROLE.search(sentence(flat, pos)) \
                    or ROLE.search(sentence(flat, pos, CLAUSE)):
                kind = "role"  # a subagent's load, counted in its dispatch
            elif HANDOFF.search(sentence(flat, pos, CLAUSE)):
                kind = "handoff"
            else:
                kind = "load" if LOAD.search(sentence(flat, pos)) else "mention"
            return kind, bool(block["case"] or labeled or OPENING.match(sentence(flat, pos))
                              or CONDITION.search(flat[:sentence_end(flat, pos, CLAUSE)]))

        def edits(pos):
            return not block["fenced"] and bool(EDITS.search(sentence(flat, pos)))

        dispatches = {}  # sentence bounds -> dispatch record
        bare = text.replace("`", " ")
        for match in [] if block["fenced"] else AGENT.finditer(bare):
            span = bounds(bare, match.start())
            if span in dispatches or not DISPATCH.search(bare[span[0]:span[1]]):
                continue
            index = max(i for i, s in enumerate(starts) if s <= match.start())
            n, _, step = block["lines"][index]
            agent = "executor" if match.group(1).lower() == "executor" else "review"
            dispatches[span] = {"external": "agent", "target": agent, "runs": None,
                                "context": row or step or block["heading"],
                                "conditional": classify(match.start())[1],
                                "table": block["table"], "line": n,
                                "section": block["heading"],
                                "edits": edits(match.start())}

        def dispatch_at(pos):
            return next((d for (a, b), d in dispatches.items() if a <= pos < b), None)

        for (n, line, step), offset in zip(block["lines"], starts):
            context = row or step or block["heading"]
            for raw, is_link, col in targets(line, block["fenced"]):
                rel, skip = resolve(skill, source, raw, is_link)
                if skip or rel == source:
                    continue
                kind, conditional = classify(offset + col)
                owner = dispatch_at(offset + col)
                if owner and not owner["runs"] and RUNS.search(text[:offset + col - 1]):
                    owner["runs"] = {"file": rel}
                yield {"to": rel, "raw": raw, "context": context, "conditional": conditional,
                       "kind": kind, "table": block["table"], "line": n,
                       "section": block["heading"], "edits": edits(offset + col)}
            if block["fenced"]:
                continue
            for match in SPAN.finditer(line):
                call = MODE.fullmatch(match.group(1))
                if call:
                    called_skill, mode = call.group(1), call.group(2)
                    mode_end = offset + match.start(1) + call.end(2)
                else:
                    skill_call = re.fullmatch(r"(varde-[a-z][a-z0-9-]*)", match.group(1))
                    following = re.match(r"\s+([a-z][a-z0-9_-]*)\b", line[match.end():])
                    if not skill_call or not following or following.group(1) in {
                            "and", "but", "or", "then", "to", "for", "with", "from",
                            "before", "after", "when", "while", "unless", "because",
                            "route"}:
                        continue
                    called_skill, mode = skill_call.group(1), following.group(1)
                    mode_end = offset + match.end() + following.end(1)
                if skill_names and called_skill not in skill_names:
                    continue
                owner = dispatch_at(offset + match.start())
                if not owner and mode == "report" and REVIEWED.search(flat):
                    owner = {"external": "agent", "target": "review", "runs": None,
                             "context": context, "table": block["table"], "line": n,
                             "conditional": classify(offset + match.start())[1],
                             "section": block["heading"],
                             "edits": edits(offset + match.start())}
                    dispatches[(-n, -n)] = owner  # an independent report review
                if owner:
                    owner["runs"] = owner["runs"] or {"skill": called_skill, "mode": mode}
                    continue
                kind, conditional = classify(offset + match.start())
                _, stop = bounds(flat, offset + match.start())
                tail = flat[mode_end:stop]
                route_word = re.search(r"\b(?:route|section)\b", tail, re.I)
                qualifier = None
                if route_word:
                    ignored = {"and", "follow", "its", "the", "a", "an", "via",
                               "through", "using", "use"}
                    words = [word.lower() for word in re.findall(
                        r"[a-z0-9]+(?:-[a-z0-9]+)*", tail[:route_word.start()], re.I)
                             if word.lower() not in ignored]
                    qualifier = " ".join(words) or None
                item = {"external": "skill", "target": f"{called_skill} {mode}",
                        "skill": called_skill, "mode": mode, "context": context,
                        "conditional": conditional, "kind": kind, "table": block["table"],
                        "line": n, "section": block["heading"],
                        "edits": edits(offset + match.start())}
                if qualifier:
                    item["qualifier"] = qualifier
                yield item
        yield from dispatches.values()


def match_route(routes, mode, qualifier=None):
    """Return a qualified route, else the route a mode names by stem or label."""
    candidates = routes
    words = set(re.findall(r"[a-z0-9]+", (qualifier or "").lower()))
    if words:
        qualified = []
        for route in routes:
            names = [route["route"], *(Path(f).stem for f in route["entry"])]
            if any(words <= set(re.findall(r"[a-z0-9]+", name.lower()))
                   for name in names):
                qualified.append(route)
        if not qualified:
            return None
        candidates = qualified
    stem = [r for r in candidates if any(Path(f).stem == mode for f in r["entry"])]
    if stem:
        return min(stem, key=lambda r: len(r["entry"]))
    word = re.compile(rf"\b{re.escape(mode)}\b", re.I)
    return next((r for r in candidates if word.search(r["route"])),
                min(candidates, key=lambda r: len(r["entry"])) if words else None)


def skip_targets(skill, source):
    """Files this file's 'skip' sentences name, to drop from this file's route."""
    text = " ".join(actual_path(skill, source).read_text(errors="replace").split("\n"))
    resolved = []
    for match in SKIP.finditer(text):
        _, stop = bounds(text, match.start())
        raw = next((r for r, is_link, _ in targets(text[match.end():stop], False)
                    if not is_link), None)
        rel, missing = resolve(skill, source, raw, False) if raw else (None, True)
        if not missing:
            resolved.append(rel)
    return resolved


def reach(loads, starts, always_only):
    reached, todo = [], list(dict.fromkeys(starts))
    while todo:
        current = todo.pop(0)
        if current in reached or current == "SKILL.md":
            continue
        reached.append(current)
        todo += [e["to"] for e in loads if e["from"] == current
                 and not (always_only and e["conditional"])]
    return reached


def depths(loads, starts):
    """Shortest hop count along load edges; a start is depth 1, SKILL.md is 0."""
    depth, todo = {}, [(s, 1) for s in dict.fromkeys(starts)]
    while todo:
        current, hop = todo.pop(0)
        if current == "SKILL.md" or depth.get(current, hop + 1) <= hop:
            continue
        depth[current] = hop
        todo += [(e["to"], hop + 1) for e in loads if e["from"] == current]
    return depth


def route_complexity(edges, loads, starts, reached, references):
    """Cyclomatic, cognitive complexity and lookups over one route's reachable
    conditional edges. A conditional edge into a reference is a lookup, excluded
    from both; a reference's own conditional edges count as its caller's
    branches at the caller's depth (no added nesting).
    """
    depth = depths(loads, starts)
    caller_depth = {}
    for e in loads:
        if e["to"] in references and e["from"] in reached:
            here = depth.get(e["from"], 0)
            if e["to"] not in caller_depth or here < caller_depth[e["to"]]:
                caller_depth[e["to"]] = here

    def branch_depth(node):
        return caller_depth[node] if node in caller_depth else depth.get(node, 0)

    conditional = [e for e in edges if e["conditional"] and e["from"] in reached]
    lookups = [e for e in conditional if e["to"] in references]
    branches = [e for e in conditional if e["to"] not in references]
    return {"cyclomatic": len(branches) + 1,
            "cognitive": sum(1 + branch_depth(e["from"]) for e in branches),
            "lookups": len(lookups)}


def analyze(skill):
    """Map one skill's own files and routes; resolve() adds cross-skill costs."""
    names = {p.parent.name for p in skill.parent.glob("*/SKILL.md")}
    skill_names = names if names - {skill.name} else set()
    files = sorted(
        str(p.relative_to(skill)) for d in DIRS for p in (skill / d).rglob("*") if p.is_file()
    )
    manifest = shared_manifest(skill.parent / "shared")
    shared_files = sorted(rel for rel, skills in manifest.items()
                           if skill.name in skills and rel not in files)
    sizes = {f: tokens(actual_path(skill, f)) for f in ["SKILL.md"] + files + shared_files}
    references = {f for f in files + shared_files
                  if file_kind(actual_path(skill, f)) == "reference"}
    sections = {}  # SKILL.md heading -> the table row that routes to it
    for line in (skill / "SKILL.md").read_text(errors="replace").split("\n"):
        if line.strip().startswith("|"):
            for heading in SECTION.findall(line):
                sections[short(heading)] = short(line.strip().strip("|").split("|")[0])
    edges, external, missing = [], [], []
    for source in ["SKILL.md"] + [f for f in files + shared_files if f.endswith(".md")]:
        for item in scan(skill, source, skill_names):
            section, edits = item.pop("section"), item.pop("edits")
            if source == "SKILL.md":
                item["route"] = item["context"] if item["table"] else sections.get(section)
                if not item["route"] and edits:
                    item["conditional"] = True  # an edit gate: only routes that edit
            if "external" in item:
                external.append({"from": source, **item})
                continue
            if not actual_path(skill, item["to"]).is_file():
                missing.append({"from": source, "line": item["line"], "target": item["raw"]})
                continue
            if item["to"] not in sizes:
                continue  # a real file outside the mapped directories
            edges.append({"from": source, "to": item["to"], "context": item["context"],
                          "conditional": item["conditional"], "kind": item["kind"],
                          "table": item["table"], "line": item["line"],
                          **({"route": item["route"]} if "route" in item else {})})

    loads = [e for e in edges if e["kind"] == "load"]
    top = [e for e in loads if e["from"] == "SKILL.md"]
    if not any(e["table"] for e in top):  # no routing table: each label is a route
        for e in top + [x for x in external if x["from"] == "SKILL.md"]:
            e["route"] = e["context"]
    routes = {}
    for e in top:
        if e["route"]:
            routes.setdefault(e["route"], []).append(e)
    everywhere = [e for e in top if not e["route"]]

    def cost(reached):
        return sizes["SKILL.md"] + sum(sizes[f] for f in reached if f.endswith(".md"))

    route_list = []
    for name, own in routes.items():
        entry = list(dict.fromkeys(e["to"] for e in own))
        dropped = {t for f in entry if f.endswith(".md") for t in skip_targets(skill, f)}
        route_loads = [e for e in loads if e["from"] not in dropped and e["to"] not in dropped]
        starts = [e["to"] for e in own + everywhere if e["to"] not in dropped]
        min_starts = [e["to"] for e in own + everywhere
                      if (e["table"] or not e["conditional"]) and e["to"] not in dropped]
        minimum = reach(route_loads, min_starts, True)
        reached = reach(route_loads, starts, False)
        route_list.append({"route": name, "entry": entry,
                           "files": reached, "min_files": minimum,
                           "min_tokens": cost(minimum), "max_tokens": cost(reached)})
        route_list[-1]["handoffs"] = sorted({
            e["to"] for e in edges if e["kind"] == "handoff"
            and e["from"] in reached and e["to"] not in reached})
        route_list[-1].update(route_complexity(edges, route_loads, starts, reached, references))
    return {"skill": skill.name, "tokens": sizes, "references": sorted(references),
            "edges": edges, "external": external,
            "routes": route_list, "structure": structure(edges, route_list),
            "findings": findings(files, edges, missing)}


class Flow:
    """Resolve inline skill modes and agent dispatches among sibling skills."""

    def __init__(self, parent):
        self.parent, self.skills, self.definitions = parent, {}, {}

    def skill(self, name):
        if name not in self.skills:
            path = self.parent / name
            self.skills[name] = analyze(path) if (path / "SKILL.md").is_file() else None
        return self.skills[name]

    def tokens(self, files):
        """Sum (skill, file) pairs; ("agents", name) is an agent definition."""
        return sum(self.definitions[f] if s == "agents" else self.skills[s]["tokens"].get(f, 0)
                   for s, f in files if s == "agents" or f.endswith(".md"))

    def calls(self, name, route, which):
        """External calls reached by a route's min or max files."""
        data, files = self.skill(name), set(route["min_files" if which == "min" else "files"])
        for x in data["external"]:
            if x.get("kind") == "handoff":
                continue
            if which == "min" and x["conditional"]:
                continue
            if x["from"] == "SKILL.md" and x.get("route") in (None, route["route"]) \
                    or x["from"] in files:
                yield x

    def journey(self, name, route, which, seen=frozenset()):
        """Return (files, inline, dispatches, unresolved) for the agent running a route."""
        seen = seen | {(name, route["route"])}
        own = route["min_files" if which == "min" else "files"]
        files = {(name, "SKILL.md")} | {(name, f) for f in own}
        inline, dispatches, unresolved = [], [], []
        for x in self.calls(name, route, which):
            if x["external"] == "agent":
                dispatches.append((name, x))
                continue
            if x["kind"] != "load":
                continue
            other = self.skill(x["skill"])
            target = match_route(other["routes"], x["mode"], x.get("qualifier")) if other else None
            if not target:
                unresolved.append(x["target"])
            elif (x["skill"], target["route"]) not in seen:
                inline.append((x["target"], f"{x['skill']}: {target['route']}"))
                more = self.journey(x["skill"], target, which, seen)
                files |= more[0]
                inline, dispatches, unresolved = (inline + more[1], dispatches + more[2],
                                                  unresolved + more[3])
        return files, inline, dispatches, unresolved

    def agent(self, name, x, which):
        """Return (runs label, files) for one dispatch; None files when unresolved."""
        definition = self.parent.parent / "agents" / AGENT_DIRS[x["target"]] / "claude.md"
        files = set()
        if definition.is_file():
            text = definition.read_text(errors="replace")
            self.definitions[x["target"]] = tokens(definition)
            files.add(("agents", x["target"]))
            match = re.search(r"^skills:\s*(.+)$", text.split("\n---", 1)[0], re.M)
            for preload in (match.group(1).split(",") if match else []):
                if self.skill(preload.strip()):
                    files.add((preload.strip(), "SKILL.md"))
        runs, data = x["runs"] or {}, self.skill(name)
        if "file" in runs:
            loads = [e for e in data["edges"] if e["kind"] == "load"]
            return runs["file"], files | {(name, f) for f in
                                          reach(loads, [runs["file"]], which == "min")}
        if runs or x["target"] == "executor":
            skill_name, mode = (runs["skill"], runs["mode"]) if runs else EXECUTOR
            other = self.skill(skill_name)
            target = match_route(other["routes"], mode) if other else None
            if not target:
                return f"{skill_name} {mode}", None
            return f"{skill_name}: {target['route']}", files | self.journey(
                skill_name, target, which)[0]
        loads = [e for e in data["edges"] if e["kind"] == "load"]
        gate = [f for f in GATE if f in data["tokens"]]
        return "review gate", files | {(name, f) for f in gate + reach(
            loads, gate[:1], which == "min")}

    def resolve(self, name):
        """Add main-agent costs and per-dispatch subagent costs to each route."""
        data = self.skill(name)
        for route in data["routes"]:
            low, high = self.journey(name, route, "min"), self.journey(name, route, "max")
            route["main_min_tokens"] = self.tokens(low[0])
            route["main_max_tokens"] = self.tokens(high[0])
            route["inline"] = [{"target": t, "resolved": r} for t, r in dict(high[1]).items()]
            route["unresolved"] = sorted(set(high[3]))
            route["handoffs"] = sorted(set(route["handoffs"]) | {
                x["target"] for x in data["external"] if x.get("kind") == "handoff"
                and (x["from"] == "SKILL.md" and x.get("route") in (None, route["route"])
                     or x["from"] in route["files"])})
            always = {(s, x["from"], x["line"]) for s, x in low[2]}
            dispatches = {}
            for source, x in high[2]:
                runs, low_files = self.agent(source, x, "min")
                _, high_files = self.agent(source, x, "max")
                item = dispatches.setdefault((x["target"], runs), {
                    "agent": x["target"], "runs": runs, "from": [], "conditional": True,
                    "min_tokens": None if low_files is None else self.tokens(low_files),
                    "max_tokens": None if high_files is None else self.tokens(high_files)})
                where = f"{source}/{x['from']}:{x['line']}" if source != name \
                    else f"{x['from']}:{x['line']}"
                if where not in item["from"]:
                    item["from"].append(where)
                if (source, x["from"], x["line"]) in always:
                    item["conditional"] = False
            route["dispatches"] = list(dispatches.values())
        return data


def findings(files, edges, missing):
    places, callers_any = {}, set()
    for e in edges:
        callers_any.add(e["to"])
        if e["kind"] in ("mention", "role"):
            continue
        place = f"SKILL.md: {e['context']}" if e["from"] == "SKILL.md" else e["from"]
        places.setdefault(e["to"], {}).setdefault(place, []).append(e)
    out = {"chain": [], "single caller": [], "shared": [], "unreferenced": [],
           "missing": missing}
    for f in files:
        callers = places.get(f, {})
        if f not in callers_any:
            out["unreferenced"].append(f)
        elif not f.startswith("references/") or not callers:
            continue
        elif len(callers) > 1:
            out["shared"].append({"file": f, "callers": sorted(callers)})
        else:
            (place, hits), = callers.items()
            always = not place.startswith("SKILL.md") and any(
                e["kind"] == "load" and not e["conditional"] for e in hits)
            out["chain" if always else "single caller"].append({"file": f, "caller": place})
    shape = structure(edges)
    out["cycle"] = [{"files": pair} for pair in shape["mutual_pairs"]]
    out["fan-out"] = [{"file": f, "links": n} for f, n in shape["links_out"].items()
                      if n >= FAN_OUT]
    out["density"] = [{"average": shape["average_links"]}] \
        if shape["average_links"] > DENSITY else []
    return out


def structure(edges, routes=None):
    """Measure file-to-file load and hand-off links, SKILL.md excluded.

    Module grouping and route complexity are separate measures, folded in here only
    for reporting; `routes`, when given, adds the two route-complexity rows.
    """
    links = sorted({(e["from"], e["to"]) for e in edges
                    if e["kind"] in ("load", "handoff") and e["from"] != "SKILL.md"})
    out = {}
    for source, _ in links:
        out[source] = out.get(source, 0) + 1
    pairs = [[a, b] for a, b in links if a < b and (b, a) in set(links)]
    top = max(out, key=lambda f: (out[f], f), default=None)
    cross_module = sum(1 for a, b in links if module_of(a) != module_of(b))
    shape = {"mutual_links": len(pairs), "mutual_pairs": pairs,
            "max_links_out": out.get(top, 0), "max_links_out_file": top,
            "average_links": round(len(links) / len(out), 2) if out else 0,
            "linking_files": len(out), "links": len(links), "links_out": out,
            "cross_module_edges": cross_module, "diagram_edges": len(edges)}
    if routes:
        shape["max_route_cyclomatic"] = max(r["cyclomatic"] for r in routes)
        shape["max_route_cognitive"] = max(r["cognitive"] for r in routes)
        widest = max(routes, key=lambda r: len(r["files"]))
        shape["max_route_files"] = len(widest["files"])
        shape["max_route_files_route"] = widest["route"]
    return shape


def structure_rows(shape):
    """Return (measure, value, target, status) rows for the Structure table."""
    rows = [
        ("Mutual links", str(shape["mutual_links"]), "0",
         "defect" if shape["mutual_links"] else "ok"),
        ("Max links out of one file",
         f"{shape['max_links_out']}" + (f" ({shape['max_links_out_file']})"
                                        if shape["max_links_out_file"] else ""),
         f"< {FAN_OUT}", "warning" if shape["max_links_out"] >= FAN_OUT else "ok"),
        ("Average links per linking file",
         f"{shape['average_links']} ({shape['links']} links, {shape['linking_files']} "
         f"file{'' if shape['linking_files'] == 1 else 's'})",
         f"<= {DENSITY}", "warning" if shape["average_links"] > DENSITY else "ok"),
        ("Cross-module edges", str(shape["cross_module_edges"]), "-", "-"),
        ("Diagram edges", str(shape["diagram_edges"]), f"<= {DIAGRAM_EDGES_WARN}",
         "warning" if shape["diagram_edges"] > DIAGRAM_EDGES_WARN else "ok"),
    ]
    if "max_route_cyclomatic" in shape:
        cyc = shape["max_route_cyclomatic"]
        rows.append(("Max route cyclomatic", str(cyc), f"<= {CYCLOMATIC_WARN}",
                     "warning" if cyc > CYCLOMATIC_WARN else "ok"))
    if "max_route_cognitive" in shape:
        cog = shape["max_route_cognitive"]
        status = ("defect" if cog > COGNITIVE_ERROR
                  else "warning" if cog > COGNITIVE_WARN else "ok")
        rows.append(("Max route cognitive", str(cog),
                     f"<= {COGNITIVE_WARN} warn, <= {COGNITIVE_ERROR} error", status))
    if "max_route_files" in shape:
        files = shape["max_route_files"]
        rows.append(("Most files reached by one route",
                     f"{files} ({shape['max_route_files_route']})",
                     f"<= {ROUTE_FILES_WARN}", "warning" if files > ROUTE_FILES_WARN else "ok"))
    return rows


def dispatch_cost(d):
    if d["min_tokens"] is None:
        return "unresolved"
    low, high = d["min_tokens"], d["max_tokens"]
    return f"~{low}" if low == high else f"~{low}-{high}"


def text_report(data):
    out = [f"== {data['skill']} (SKILL.md ~{data['tokens']['SKILL.md']} tokens)", "Routes:"]
    for r in data["routes"]:
        out.append(f"  {r['route']}  [~{r['min_tokens']}-{r['max_tokens']} tokens with SKILL.md;"
                   f" main agent ~{r['main_min_tokens']}-{r['main_max_tokens']}]")
        out += [f"    {sized_label(data, f, f, '')}" for f in r["files"]]
        out += [f"    handoff: {f}" for f in r["handoffs"]]
        out += [f"    inline: {x['target']} -> {x['resolved']}" for x in r["inline"]]
        out += [f"    unresolved: {target}" for target in r["unresolved"]]
        for d in r["dispatches"]:
            out.append(f"    dispatch {d['agent']}{' (conditional)' * d['conditional']}:"
                       f" {d['runs']}, {dispatch_cost(d)} per dispatch, from {', '.join(d['from'])}")
    if not data["routes"]:
        out.append("  (none)")
    out.append("Structure:")
    out += [f"  {m}: {v} (target {t}) {st}" for m, v, t, st in structure_rows(data["structure"])]
    out.append("Findings:")
    for kind, items in data["findings"].items():
        for item in items:
            if kind == "missing":
                detail = f"{item['from']}:{item['line']} -> {item['target']}"
            elif kind == "shared":
                detail = f"{item['file']} <- {'; '.join(item['callers'])}"
            elif kind == "unreferenced":
                detail = item
            elif kind == "cycle":
                detail = " <-> ".join(item["files"])
            elif kind == "fan-out":
                detail = f"{item['file']} ({item['links']} links out, target < {FAN_OUT})"
            elif kind == "density":
                detail = f"average {item['average']} links per linking file (target <= {DENSITY})"
            else:
                detail = f"{item['file']} <- {item['caller']}"
            out.append(f"  {kind}: {detail}")
    return "\n".join(out)


def escape_label(text):
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def module_groups(data):
    """Every non-reference file below SKILL.md, grouped by module_of, each list
    alphabetical. A module of only reference files has no key, so it drops
    out of the overview and gets no section of its own."""
    refs = set(data["references"])
    groups = {}
    for name in data["tokens"]:
        if name != "SKILL.md" and name not in refs:
            groups.setdefault(module_of(name), []).append(name)
    return {m: sorted(files) for m, files in groups.items()}


def fold(data):
    """Per procedure file: the reference files transitively folded into it,
    and the non-reference files reached by following load/handoff edges
    through those references. A reference has no node of its own, so its
    outgoing edges attach to the procedure that folds it."""
    refs = set(data["references"])
    by_from = {}
    for e in data["edges"]:
        if e["kind"] in ("load", "handoff") and e["from"] != "SKILL.md":
            by_from.setdefault(e["from"], []).append(e)

    def walk(node, visited):
        folded, dests = set(), []
        for e in by_from.get(node, []):
            to = e["to"]
            if to in visited:
                continue
            if to in refs:
                folded.add(to)
                sub_folded, sub_dests = walk(to, visited | {to})
                folded |= sub_folded
                dests += sub_dests
            else:
                dests.append((to, e))
        return folded, dests

    return {name: walk(name, {name}) for name in data["tokens"]
            if name != "SKILL.md" and name not in refs}


def module_edge_pairs(folds):
    """(from-module, to-module) -> edge count, over folded procedure edges."""
    pairs = {}
    for proc, (_, dests) in folds.items():
        for dest, _ in dests:
            key = (module_of(proc), module_of(dest))
            pairs[key] = pairs.get(key, 0) + 1
    return pairs


def module_overview_mermaid(groups, pairs):
    """One node per module, one aggregated edge per module pair with its edge count."""
    ids = {m: f"m{i}" for i, m in enumerate(sorted(groups))}
    out = ["flowchart TD"]
    for m in sorted(groups):
        count = len(groups[m])
        out.append(f'  {ids[m]}["{m} ({count} file{"" if count == 1 else "s"})"]')
    for (a, b), count in sorted(pairs.items()):
        if a != b:
            out.append(f'  {ids[a]} -->|"{count}"| {ids[b]}')
    return "\n".join(out)


def sized_label(data, name, text, unit=" tok"):
    """Text plus the file's estimated size; non-Markdown files carry none."""
    return f"{text} (~{data['tokens'][name]}{unit})" if name.endswith(".md") else text


def module_mermaid(data, groups, pairs, folds, name):
    """This module's own procedures, plus one node per other module it links
    to or from. Each procedure's label folds in every reference it
    transitively points to; a reference's own edges attach to that procedure."""
    ids = {f: f"n{i}" for i, f in enumerate(groups[name])}
    out = ["flowchart TD"]
    for f in groups[name]:
        folded, _ = folds[f]
        lines = [sized_label(data, f, escape_label(f))]
        lines += [f"ref: {escape_label(r)} (~{data['tokens'][r]} tok)" for r in sorted(folded)]
        out.append(f'  {ids[f]}["{"<br/>".join(lines)}"]')
    others = sorted({b for (a, b) in pairs if a == name and b != name}
                    | {a for (a, b) in pairs if b == name and a != name})
    for m in others:
        ids[m] = f"n{len(ids)}"
        out.append(f'  {ids[m]}["{m}"]')
    seen = set()
    for proc in sorted(folds):
        from_module = module_of(proc)
        _, dests = folds[proc]
        for dest, e in sorted(dests, key=lambda t: t[0]):
            to_module = module_of(dest)
            if name not in (from_module, to_module):
                continue
            source = ids[proc] if from_module == name else ids[from_module]
            target = ids[dest] if to_module == name else ids[to_module]
            if (source, target) in seen:
                continue
            seen.add((source, target))
            arrow = "==>" if e["kind"] == "handoff" else "-.->" if e["conditional"] else "-->"
            out.append(f"  {source} {arrow} {target}")
    return "\n".join(out)


def mermaid(data):
    ids = {}

    def node(name):
        return ids.setdefault(name, f"n{len(ids)}")

    label = escape_label

    out = [f"%% {data['skill']}", "flowchart TD",
           f'  {node("SKILL.md")}["SKILL.md (~{data["tokens"]["SKILL.md"]} tok)"]']
    for name in data["tokens"]:
        if name != "SKILL.md":
            out.append(f'  {node(name)}["{sized_label(data, name, label(name))}"]')
    for r in data["routes"]:
        route = node("route: " + r["route"])
        out.append(f'  {route}(["{label(r["route"])}"])')
        out.append(f"  {node('SKILL.md')} --> {route}")
    seen = set()
    for e in data["edges"] + data["external"]:
        if e.get("kind") in ("mention", "role"):
            continue
        routed = bool(e.get("route"))
        source = node("route: " + e["route"]) if routed else node(e["from"])
        if "external" in e:
            text = e["target"] if e["external"] == "skill" else f"agent: {e['target']}"
            target = node("external: " + text)
            key = (source, target, e["context"])
            if target not in seen:
                seen.add(target)
                out.append(f'  {target}[["{label(text)}"]]')
        else:
            target = node(e["to"])
            key = (source, target, e["context"])
        if key in seen:
            continue
        seen.add(key)
        if routed and "external" not in e:
            out.append(f"  {source} --> {target}")
            continue
        arrow = "==>" if e.get("kind") == "handoff" else "-.->" if e["conditional"] else "-->"
        out.append(f'  {source} {arrow}|"{label(e["context"])}"| {target}')
    return "\n".join(out)


def files_tree(data):
    references = sorted(f for f in data["tokens"]
                        if f.startswith("references/") and f.endswith(".md"))
    children = {"SKILL.md": []}
    for ref in references:
        stem = Path(ref).stem
        parents = [candidate for candidate in references
                   if stem.startswith(Path(candidate).stem + "-")]
        parent = max(parents, key=lambda candidate: len(Path(candidate).stem),
                     default="SKILL.md")
        children.setdefault(parent, []).append(ref)
        children.setdefault(ref, [])

    routes = {ref: [r["route"] for r in data["routes"] if ref in r["files"]]
              for ref in references}
    root_routes = [r["route"] for r in data["routes"]]

    def render(ref, depth):
        entering = root_routes if ref == "SKILL.md" else routes[ref]
        line = f"{'  ' * depth}- {ref} (~{data['tokens'][ref]} tok; "
        line += f"routes: {', '.join(entering) if entering else '-'})"
        lines = [line]
        for child in sorted(children[ref]):
            lines.extend(render(child, depth + 1))
        return lines

    return render("SKILL.md", 0)


def flow_doc(data, skill):
    folds = fold(data)
    groups, pairs = module_groups(data), module_edge_pairs(folds)
    out = [f"# {data['skill']} flow", "",
           "Generated for human readers; agents do not load this file. Regenerate",
           "with skill-flow.py --write from varde-agent-doc-authoring. Dotted edges",
           "are conditional loads; min tokens follow only solid edges. Thick edges",
           "are hand-offs to a later stage, outside min and max. Double-bordered",
           "nodes are skill modes run inline or agent dispatches. Min and max count",
           "this skill; main adds modes the main agent runs inline, each file once.",
           "Subagents are per dispatch (multiply by the dispatch count); * marks a",
           "conditional dispatch. Module overview first, then one diagram per module."]
    out += ["", "## Files", ""] + files_tree(data)
    out += ["", "```mermaid", module_overview_mermaid(groups, pairs), "```"]
    for name in sorted(groups):
        out += ["", f"### {name}", "", "```mermaid",
               module_mermaid(data, groups, pairs, folds, name), "```"]
    out += ["", "## Routes", "",
           "| Route | Min tokens | Max tokens | Main min | Main max | Subagents per dispatch"
           " | Lookups | Files |", "|---|---|---|---|---|---|---|---|"]
    for r in data["routes"]:
        name = r["route"].replace("|", "\\|")
        agents = ", ".join(f"{d['agent']}{'*' * d['conditional']} {dispatch_cost(d)}"
                           for d in r["dispatches"]) or "-"
        out.append(f"| {name} | ~{r['min_tokens']} | ~{r['max_tokens']} |"
                   f" ~{r['main_min_tokens']} | ~{r['main_max_tokens']} | {agents} |"
                   f" {r['lookups']} | {', '.join(r['files']) or '-'} |")
    findings = [line.strip() for line in
                text_report(data).split("Findings:", 1)[1].splitlines()[1:]]
    shape = [f for f in findings if f.startswith(STRUCTURE)]
    out += ["", "## Structure", "", "| Measure | Value | Target | Status |", "|---|---|---|---|"]
    out += [f"| {m} | {v} | {t} | {st} |" for m, v, t, st in structure_rows(data["structure"])]
    out += [""] + [f"- {line}" for line in shape] if shape else []
    out += ["", "## Findings", ""]
    out += [f"- {line}" for line in findings if line not in shape] or ["None."]
    return "\n".join(out) + "\n"


def main(args):
    mode = "text"
    if args and args[0] in ("--mermaid", "--json", "--write", "--check"):
        mode, args = args[0][2:], args[1:]
    if not args or any(a.startswith("--") for a in args):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    skills, flows = [], {}
    for arg in args:
        skill = Path(arg)
        if not (skill / "SKILL.md").is_file():
            print(f"skill-flow.py: not a skill directory: {arg}", file=sys.stderr)
            return 2
        skill = skill.resolve()
        flow = flows.setdefault(skill.parent, Flow(skill.parent))
        skills.append(flow.resolve(skill.name))
    if mode in ("write", "check"):
        stale = 0
        for arg, data in zip(args, skills):
            target, doc = Path(arg) / "FLOW.md", flow_doc(data, Path(arg).resolve())
            if mode == "write":
                target.write_text(doc)
            elif not target.is_file() or target.read_text() != doc:
                stale += 1
                print(f"stale: {target} (run skill-flow.py --write {arg})")
        return 1 if stale else 0
    if mode == "json":
        print(json.dumps(skills, indent=2))
    else:
        render = mermaid if mode == "mermaid" else text_report
        print("\n\n".join(render(s) for s in skills))
    return 1 if any(s["findings"]["missing"] for s in skills) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
