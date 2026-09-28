#!/usr/bin/env bash
set -euo pipefail

# Each vendored reference is copied into every consuming skill; most content is
# meant to differ, but the sections named in MANIFEST below are the shared
# contract and must stay byte-identical (README.md:100-115 explains why).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# <reference filename>:<section>[,<section>...]
# `*` means the whole file must match byte for byte. Join renamed copies of one
# reference with `|`.
#
# The memory-location resolution is inlined into each SKILL.md's Gotchas
# instead of vendored; it is pinned below by exact paragraph text.
MANIFEST=(
  "review-gates.md:*"
  "review-gate-record.md:*"
  "review-gate-plan.md:*"
  "review-gate-worktree.md:*"
  "varde-code.md:__preamble__,Fallback rule"
  "varde-workflow-cli.md:Fallback rule"
)

cd "$SKILLS_DIR"

status=0
for entry in "${MANIFEST[@]}"; do
  base="${entry%%:*}"
  sections="${entry#*:}"
  if ! SECTIONS="$sections" BASE="$base" python3 - <<'PY'
import glob, hashlib, os, re, sys

base = os.environ["BASE"]
wanted = os.environ["SECTIONS"].split(",")
files = sorted(f for name in base.split("|") for f in glob.glob(f"varde-*/references/{name}"))

if len(files) < 2:
    print(f"FAIL: {base} has {len(files)} copies; nothing to compare", file=sys.stderr)
    sys.exit(1)


def split_sections(text):
    parts = re.split(r"(?m)^(## .+)$", text)
    out = {"__preamble__": parts[0]}
    for i in range(1, len(parts), 2):
        out[parts[i][3:].strip()] = parts[i + 1]
    return out


def digest(s):
    return hashlib.sha256(s.strip().encode()).hexdigest()[:12]


ok = True
for name in wanted:
    seen = {}
    for f in files:
        text = open(f).read()
        body = text if name == "*" else split_sections(text).get(name)
        if body is None:
            continue
        seen.setdefault(digest(body), []).append(f)
    if name != "*" and not seen:
        print(f"FAIL: {base} — no copy defines section '{name}'", file=sys.stderr)
        ok = False
        continue
    if len(seen) > 1:
        label = "whole file" if name == "*" else f"'{name}'"
        print(f"FAIL: {base} — {label} differs across copies:", file=sys.stderr)
        for h, group in sorted(seen.items()):
            for f in group:
                print(f"         {h}  {f}", file=sys.stderr)
        ok = False
    else:
        covered = sum(len(v) for v in seen.values())
        label = "whole file" if name == "*" else name
        print(f"  {base}: {label} in step across {covered}/{len(files)} copies")

sys.exit(0 if ok else 1)
PY
  then
    status=1
  fi
done

# Every SKILL.md that resolves memory locations must inline this exact
# paragraph (whitespace-insensitive: markdown line-wrapping differs by file).
if ! python3 - <<'PY'
import glob, re, sys

paragraph = (
    "`<working>` (local, uncommitted) and `<knowledge>` (committed): resolve once "
    "before first use with `varde-workflow paths --json`; use its absolute "
    "`data.working`/`data.knowledge` paths for this session and pass them to "
    "subagents. If the command fails, retry it once with escalated access; if it "
    "still fails, ask the user for the paths. Do not guess storage paths. A "
    "location outside the repo skips git ops (`check-ignore`, `mv`, `status`); "
    "use plain file ops."
)
normalized_paragraph = re.sub(r"\s+", " ", paragraph).strip()

checked = 0
ok = True
for skill_md in sorted(glob.glob("varde-*/SKILL.md")):
    text = open(skill_md, encoding="utf-8").read()
    if "resolve once" not in text or "data.working" not in text:
        continue
    checked += 1
    normalized_text = re.sub(r"\s+", " ", text)
    if normalized_paragraph not in normalized_text:
        print(f"FAIL: {skill_md}'s memory paragraph does not match the pinned text verbatim", file=sys.stderr)
        ok = False

if checked == 0:
    print("FAIL: no SKILL.md inlines the memory-location paragraph", file=sys.stderr)
    ok = False
else:
    print(f"  memory-location paragraph: pinned text matched in {checked} SKILL.md file(s)")

sys.exit(0 if ok else 1)
PY
then
  status=1
fi

if [ "$status" -ne 0 ]; then
  echo "FAIL: vendored copies drifted — apply the fix to every copy, not one." >&2
  exit 1
fi

echo "Vendored references agree on every shared contract section."
