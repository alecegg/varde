#!/usr/bin/env bash
# Shared sources keep exactly one copy of their text.
#   R1 MANIFEST lines are well formed.
#   R2 no skill shadows a shared file or reference basename.
#   R3/R4 no block of text from a shared markdown file, and no 8+ word sentence
#      of its prose, also appears in another skill file, shared file, or
#      reference (headings, comments, and fence delimiters are skipped;
#      <placeholders> are normalized).
# SKILLS_DIR overrides the skills tree (used to test the test on a copy).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${SKILLS_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
export SKILLS_DIR

python3 - <<'PY'
import os, re, sys
from pathlib import Path

root = Path(os.environ["SKILLS_DIR"]).resolve()
shared = root / "shared"
errors = []

# R1 and R2: MANIFEST shape and ownership.
seen = set()
recipients_of = {}
for n, line in enumerate((shared / "MANIFEST").read_text().splitlines(), 1):
    if not line.strip():
        continue
    if not re.fullmatch(r"\S+( \S+)+", line):
        errors.append(f"R1 MANIFEST:{n}: line must be single-space separated '<path> <skill>...'")
    parts = line.split()
    rel, skills = parts[0], parts[1:]
    where = f"MANIFEST:{n}"
    if rel in seen:
        errors.append(f"R1 {where}: duplicate path {rel}")
    seen.add(rel)
    if not (shared / rel).is_file():
        errors.append(f"R1 {where}: skills/shared/{rel} does not exist")
    if len(set(skills)) < 2 or len(set(skills)) != len(skills):
        errors.append(f"R1 {where}: {rel} needs at least two distinct recipients")
    for skill in skills:
        if not (root / skill / "SKILL.md").is_file():
            errors.append(f"R1 {where}: recipient {skill} has no SKILL.md")
        if (root / skill / rel).exists():
            errors.append(f"R2 {where}: {skill} owns its own {rel}")
    recipients_of[rel] = skills

shared_names = {p.name for p in (shared / "references").glob("*.md")}
for ref in sorted(root.glob("varde-*/references/*.md")):
    if ref.name in shared_names:
        errors.append(f"R2 {ref.relative_to(root)} shares a basename with a shared reference")

# R3 and R4: text blocks.
def scanned():
    files = list(shared.rglob("*.md"))
    files += root.glob("varde-*/SKILL.md")
    files += root.glob("varde-*/references/*.md")
    for f in sorted(set(files)):
        rel = f.relative_to(root)
        if f.name == "FLOW.md" or any(
            part in ("evals", "tests") or part.endswith("-workspace") for part in rel.parts
        ):
            continue
        yield f

LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
PLACEHOLDER = re.compile(r"<[^<>\n]*>")

def norm(text):
    text = re.sub(r"^\s*(?:>\s*)*", "", text)
    text = LIST.sub("", text)
    return re.sub(r"\s+", " ", PLACEHOLDER.sub("<>", text)).strip().casefold()

def blocks(path):
    """Return (line, kind, text) for prose, list items, table rows, fenced lines."""
    out, cur, start = [], [], 0
    in_fence = in_comment = False

    def flush():
        nonlocal cur
        if cur:
            text = norm(" ".join(cur))
            kind = "table" if text.startswith("|") else "prose"
            if len(text.split()) >= (4 if kind == "table" else 8):
                out.append((start, kind, text))
        cur = []

    for n, raw in enumerate(path.read_text().splitlines(), 1):
        s = raw.strip()
        if in_fence:
            if s.startswith("```") or s.startswith("~~~"):
                in_fence = False
            elif len(norm(s).split()) >= 3:
                out.append((n, "fence", norm(s)))
            continue
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("```") or s.startswith("~~~"):
            flush(); in_fence = True; continue
        if s.startswith("<!--"):
            flush(); in_comment = "-->" not in s; continue
        if not s or s.startswith("#"):
            flush(); continue
        if s.startswith("|") or LIST.match(raw):
            flush()
            cur, start = [s], n
            if s.startswith("|"):
                flush()
            continue
        if not cur:
            start = n
        cur.append(s)
    flush()
    return out

index = {}
joined = {}
sentences = []
for f in scanned():
    rel = str(f.relative_to(root))
    found = blocks(f)
    joined[rel] = "\n".join(text for _, _, text in found)
    for line, kind, text in found:
        index.setdefault(text, []).append((rel, line))
        if kind == "prose" and rel.startswith("shared/"):
            for sentence in re.split(r"[.;:](?=\s|$)", text):
                sentence = sentence.strip()
                if len(sentence.split()) >= 8:
                    sentences.append((rel, line, sentence))

for rel, line, sentence in sentences:
    for other, text in joined.items():
        if other != rel and sentence in text:
            errors.append(f"R3 sentence from {rel}:{line} also in {other}: {sentence[:70]}")

for text, places in index.items():
    in_shared = [p for p in places if p[0].startswith("shared/")]
    if in_shared and len(places) > 1:
        where = ", ".join(f"{f}:{l}" for f, l in places)
        errors.append(f"R3 duplicated text ({where}): {text[:70]}")

if errors:
    print("FAIL: shared sources are not single-source:", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)
print("shared-single-source: MANIFEST and shared text are single-source.")
PY
