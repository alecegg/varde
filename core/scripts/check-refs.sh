#!/usr/bin/env bash
# Guards the reference invariants that varde setup sync can silently break.
#
# Each skill is a SKILL.md over one flat references/ directory, and sync
# installs each skill dir. So every pointer a shipped file names must resolve
# inside that same skill — a path that only resolves in the source tree dangles
# on a user's machine.
#
# Runs varde setup sync into a temp dir for structural checks, so they see
# exactly what an end user receives. The first run also compiles varde once.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$REPO_ROOT/core/tests/lib/repo.sh"

# Second invariant: every backticked references//assets//scripts/ path inside a
# skill must resolve to a real file. A pointer is tried against each ancestor
# directory of the file holding it, so both mode-root-relative and
# skill-root-relative styles are accepted — but a path resolving nowhere is an
# instruction the agent cannot follow. The one pointer allowed to leave the
# skill is a `../<skill>/SKILL.md` load line, and only to the installed skill
# the citing skill declares.
check_no_stale_skill() {
  python3 - "$1" <<'PYEOF'
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
legacy = "varde-" + "change"
paths = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "-z"], text=False
).split(b"\0")
found = []
for raw in paths:
    if not raw:
        continue
    relative = raw.decode()
    if relative.startswith("learn/ledgers/"):
        continue
    path = root / relative
    try:
        content = path.read_bytes()
    except OSError:
        continue
    if legacy.encode() in content:
        found.append(relative)
if found:
    print("Tracked files retain the retired skill name:", file=sys.stderr)
    for relative in found:
        print(f"  {relative}", file=sys.stderr)
    raise SystemExit(1)
PYEOF
}

check_pointers() {
  python3 - "$1" <<'PYEOF'
import os, re, sys

root = sys.argv[1]
# Group 1 is the first whitespace-delimited token of the backtick span, so
# `scripts/x.sh <arg>` is checked as `scripts/x.sh`.
pattern = re.compile(r'`([^`\s]+)[^`\n]*`')
link_pattern = re.compile(r'\]\(([^)]+)\)')
cross_skill_re = re.compile(r'^varde-[a-z0-9-]+/')
# A load line: `../<skill>/SKILL.md` from SKILL.md, `../../<skill>/SKILL.md`
# from a leaf reference. Resolving the path enforces the relative depth.
load_line_re = re.compile(r'^(?:\.\./)+(varde-[a-z0-9-]+)/SKILL\.md$')
broken = []

# Bare filenames that legitimately name something outside the skill.
EXTERNAL = {
    'SKILL.md', 'README.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
    'plan.md', 'index.md', 'log.md', 'review.md', 'notes.md', 'handoff.md',
    'logic.html', 'package.json', 'Makefile',
}


BARE_EXTENSION_RE = re.compile(r'^\.[A-Za-z0-9]+$')


def is_candidate(target):
    if target.endswith('/') or '<' in target or '>' in target:
        # A directory mention or a template placeholder, not a file to resolve.
        return False
    if BARE_EXTENSION_RE.match(target):
        return False  # prose about a file type (`.md` files), not a path
    # Any extension is accepted under these three dirs; elsewhere only a
    # recognized doc/script extension marks a token as a path worth checking.
    return (
        target.startswith(('references/', 'assets/', 'scripts/'))
        or '../' in target
        or cross_skill_re.match(target)
        or re.search(r'\.(?:md|py|sh)$', target)
    )


def declared_skills(skill):
    # requires/recommends are read as frontmatter text, not through the lint
    # schema.
    names = set()
    try:
        frontmatter = open(os.path.join(root, skill, 'SKILL.md'), errors='replace').read()
    except OSError:
        return names
    for match in re.finditer(r'^(?:requires|recommends):\s*\[([^\]]*)\]', frontmatter, re.M):
        names.update(name.strip() for name in match.group(1).split(',') if name.strip())
    return names


def has_conditional_marker(text, skill, target):
    # The accepted way to load a skill the citing skill does not declare is a
    # sentence that opens "If `<skill>` is installed,", possibly behind a list
    # marker (`1. `, `- `, `* `).
    marker = 'If `%s` is installed,' % skill
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        if target in sentence and re.match(r'^\s*(?:(?:\d+\.|[-*])\s*)?' + re.escape(marker), sentence):
            return True
    return False


for skill in sorted(d for d in os.listdir(root) if d.startswith('varde-')):
    base = os.path.join(root, skill)
    if not os.path.isdir(base):
        continue
    declared = declared_skills(skill)
    files = {
        os.path.relpath(os.path.join(dirpath, name), base)
        for dirpath, _, names in os.walk(base)
        for name in names
    }
    for rel in sorted(f for f in files if f.endswith('.md')):
        parts = rel.split('/')
        text = open(os.path.join(base, rel), errors='replace').read()
        basenames = {f.rsplit('/', 1)[-1] for f in files}
        for target in pattern.findall(text):
            if not is_candidate(target):
                continue
            if cross_skill_re.match(target):
                broken.append("%s/%s -> %s (names another skill's files)"
                              % (skill, rel, target))
                continue
            if '../' in target:
                load = load_line_re.match(target)
                if load:
                    loaded = load.group(1)
                    resolved = os.path.normpath(
                        os.path.join(os.path.dirname(os.path.join(skill, rel)), target))
                    if (resolved != os.path.join(loaded, 'SKILL.md')
                            or not os.path.isfile(os.path.join(root, resolved))):
                        broken.append(
                            "%s/%s -> %s (resolves to no installed %s/SKILL.md; the path is "
                            "relative to the citing file)"
                            % (skill, rel, target, loaded))
                    elif (loaded != skill and loaded not in declared
                          and not has_conditional_marker(text, loaded, target)):
                        broken.append(
                            "%s/%s -> %s (undeclared skill: add %s to requires or recommends, "
                            'or open the load with "If `%s` is installed,")'
                            % (skill, rel, target, loaded, loaded))
                    continue
                # Any other ../ path must resolve to a real file without
                # climbing above the skill root — the installed skill is the
                # whole world.
                if not any(
                    not os.path.normpath(os.path.join('/'.join(parts[:i]), target)).startswith('..')
                    and os.path.normpath(os.path.join('/'.join(parts[:i]), target)) in files
                    for i in range(len(parts))
                ):
                    broken.append("%s/%s -> %s (escapes the skill or resolves to no file)"
                                  % (skill, rel, target))
                continue
            if not target.startswith(('references/', 'assets/', 'scripts/')):
                # A bare filename. Most are legitimate prose about files outside
                # the skill; but a leftover like `SCOPE.md` after a rename reads
                # as an instruction and resolves to nothing, which the
                # directory-prefixed check above never sees.
                if '/' in target or target in EXTERNAL or target in basenames:
                    continue
                broken.append("%s/%s -> %s (bare name, resolves to no file)"
                              % (skill, rel, target))
                continue
            if not any(
                os.path.normpath(os.path.join('/'.join(parts[:i]), target)) in files
                for i in range(len(parts))
            ):
                broken.append("%s/%s -> %s" % (skill, rel, target))

        # Relative markdown link targets must also resolve. Skip URLs,
        # #anchors, absolute /... knowledge links, and <placeholder> paths.
        for raw_link in link_pattern.findall(text):
            link = raw_link.split()[0] if raw_link.split() else ''
            if not link or link.startswith(('#', '/', '<')):
                continue
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', link):
                continue  # scheme:// URL, mailto:, etc.
            link = link.split('#', 1)[0]
            if not link:
                continue
            doc_dir = '/'.join(parts[:-1])
            candidate = os.path.normpath(os.path.join(doc_dir, link))
            if candidate.startswith('..') or candidate not in files:
                broken.append("%s/%s -> %s (markdown link target)"
                              % (skill, rel, link))

if broken:
    print("Broken checked reference pointers (backticked candidates or relative Markdown links):", file=sys.stderr)
    for entry in sorted(set(broken)):
        print("  " + entry, file=sys.stderr)
    print("Fix: point at the real file; keep illustrative paths in plain prose.", file=sys.stderr)
    raise SystemExit(1)
PYEOF
}

# Source-tree how-topic checks: every `how: <step> - ...` pointer in a SKILL.md
# names a topic file `*/src/*/how/<skill>/<step>.md`, every topic file is named
# by a pointer or listed (`how/<skill>/<step>`) in the tracked
# `core/how-unpointed.txt` (no-pointer baselines), and no topic id is retired in
# a changelog.jsonl under the optional baselines dir $2 (no default).
check_how() {
  python3 - "$1" "${2:-}" <<'PYEOF'
import json, re, sys
from pathlib import Path

root = Path(sys.argv[1])
baselines = Path(sys.argv[2]) if sys.argv[2] else None
pointer_re = re.compile(r'^\s*(?:[-*]\s+)?how:\s+([a-z0-9-]+)\s+-\s', re.M)
pointers = {
    f"{path.parent.name}/{step}"
    for path in root.glob('*/src/*/skills/*/SKILL.md')
    for step in pointer_re.findall(path.read_text(errors='replace'))
}
topics = {
    f"{path.parent.name}/{path.stem}"
    for path in root.glob('*/src/*/how/*/*.md')
}
unpointed = root / 'core' / 'how-unpointed.txt'
listed = set(unpointed.read_text().split()) if unpointed.is_file() else set()
listed = {line.removeprefix('how/') for line in listed}
retired = set()
for log in (baselines.glob('*/changelog.jsonl') if baselines else []):
    for line in log.read_text().splitlines():
        entry = json.loads(line) if line.strip() else {}
        if entry.get('status') == 'retired' and entry.get('step'):
            retired.add(entry['step'])
problems = (
    [f"how: pointer {i} has no topic file" for i in sorted(pointers - topics)]
    + [f"topic {i} is named by no how: pointer (orphan: no pointer, not in core/how-unpointed.txt)" for i in sorted(topics - pointers - listed)]
    + [f"topic {i} reuses a retired id" for i in sorted(topics & retired)]
)
if problems:
    print("Broken how topics:", file=sys.stderr)
    for problem in problems:
        print("  " + problem, file=sys.stderr)
    raise SystemExit(1)
PYEOF
}

# The pointer check also runs on its own against an arbitrary skills root, so
# tests/check-refs-load-line.sh can drive it with fixtures.
if [ "${1:-}" = "--check-no-stale-skill" ]; then
  check_no_stale_skill "${2:?usage: check-refs.sh --check-no-stale-skill <repo-root>}"
  exit 0
fi
if [ "${1:-}" = "--check-pointers" ]; then
  check_pointers "${2:?usage: check-refs.sh --check-pointers <installed-skills-dir>}"
  exit 0
fi

if [ "${1:-}" = "--check-how" ]; then
  check_how "${2:?usage: check-refs.sh --check-how <repo-root> [<baselines-dir>]}" "${3:-}"
  exit 0
fi

"$REPO_ROOT/core/tests/check-refs-stale-skill.sh"
check_no_stale_skill "$REPO_ROOT"
check_how "$REPO_ROOT"
echo "Every how: pointer has a topic file, no topic is orphaned (neither pointed at nor in core/how-unpointed.txt) or reuses a retired id."
TMP="$(mktemp -d "${TMPDIR:-/tmp}/check-refs.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

if [[ -n "${VARDE_BIN:-}" ]]; then
  VARDE=("$VARDE_BIN")
else
  VARDE=(uv run --locked --project "$REPO_ROOT" varde)
fi

mkdir -p "$TMP/home"
HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/xdg" VARDE_CONFIG_DIR="$TMP/home/config" \
  VARDE_AGENTS_OPENCODE_VERSION=1 \
  "${VARDE[@]}" setup sync --skills-dir "$TMP/skills" --agents-dir "$TMP/agents" --harnesses none >/dev/null

synced_skill_count="$(find "$TMP/skills" -mindepth 1 -maxdepth 1 -type d -name 'varde-*' | wc -l | tr -d ' ')"
if [ "$synced_skill_count" -ne 26 ]; then
  echo "expected 26 synced skills, found $synced_skill_count" >&2
  exit 1
fi

# First structural check: an installed skill is a SKILL.md over at most one
# level of references/, scripts/, and assets/. Check directories as well as
# files — a leftover empty directory tree is the visible shape of the layout
# even when nothing tracked lives in it, and a files-only check walks past it.
# The synced `how/` topics and `step_tools/` (with one `<skill>/` level) are
# part of an installed skill so the loop edits what the harness reads.
nested="$(find "$TMP/skills"/varde-* -mindepth 2 -type d | grep -vE '/step_tools/[^/]+$' || true)"
if [ -n "$nested" ]; then
  echo "Installed skills contain a directory below the reference level:" >&2
  printf '%s\n' "$nested" | sed "s#$TMP/##" >&2
  exit 1
fi
allowed_top='/(references|scripts|assets|starters|how|step_tools)$'
if find "$TMP/skills"/varde-* -mindepth 1 -maxdepth 1 -type d |
  grep -vE "$allowed_top" | grep -q .; then
  echo "Installed skills contain an unexpected top-level directory:" >&2
  find "$TMP/skills"/varde-* -mindepth 1 -maxdepth 1 -type d |
    grep -vE "$allowed_top" | sed "s#$TMP/##" >&2
  exit 1
fi
echo "Every installed skill is a SKILL.md over one flat reference level."

# First invariant: every SKILL.md description must be a single-line scalar.
# A YAML folded scalar (`description: >`) is valid YAML, but some harnesses read
# frontmatter with a line-based regex instead of a YAML parser and end up
# showing the literal ">" as the entire description, so the skill reads as blank
# in the skill picker.
description_errors=""
all_skill_dirs=()
while IFS= read -r skill_dir; do
  all_skill_dirs+=("$skill_dir")
  if grep -n "^description: *[>|]" "$skill_dir/SKILL.md" >/dev/null 2>&1; then
    description_errors+="$skill_dir/SKILL.md\n"
  fi
done < <(skill_dirs)
if [ "${#all_skill_dirs[@]}" -ne 26 ]; then
  echo "expected 26 source skills, found ${#all_skill_dirs[@]}" >&2
  exit 1
fi
if [ -n "$description_errors" ]; then
  echo "SKILL.md descriptions must be one single-line scalar:" >&2
  printf '%b' "$description_errors" >&2
  echo "Fix: collapse to one double-quoted line; lead with the user's outcome verbs and end \`Not for <nearest sibling task>\` when a sibling skill overlaps." >&2
  exit 1
fi
echo "All SKILL.md descriptions are single-line scalars."

# Second invariant, defined above as check_pointers.
if ! check_pointers "$TMP/skills"; then
  exit 1
fi
echo "Checked backticked file paths and relative Markdown links resolve; bare paths in prose or commands are not checked."

# Third invariant: every shipped script is named by a markdown file in its own
# skill. An agent learns a script exists only where a document names it — in
# SKILL.md for inline skills, in the mode reference that runs it for
# dispatchers. An unnamed script is dead weight that ships to every install.
orphans=""
for script in "$TMP"/varde-*/scripts/*; do
  [ -f "$script" ] || continue
  skill_dir="${script%/scripts/*}"
  if ! grep -rqF --include='*.md' "$(basename "$script")" "$skill_dir"; then
    orphans="$orphans${script#"$TMP"/}"$'\n'
  fi
done
if [ -n "$orphans" ]; then
  echo "Shipped scripts that no document in their skill names:" >&2
  printf '%s' "$orphans" >&2
  echo "Fix: name the script where the agent runs it, or delete it." >&2
  exit 1
fi
echo "Every shipped script is named where it runs."

# Fourth invariant: every shipped reference is named by some shipped file
# (reachability, formerly tests/consolidated-workflows.sh), and no active
# file still names a retired skill — read from core/scripts/RETIRED rather than a
# second hardcoded list.
command -v rg >/dev/null 2>&1 || { echo "ripgrep (rg) is required" >&2; exit 1; }

for skill_dir in "$TMP"/skills/varde-*/; do
  skill="$(basename "$skill_dir")"
  for ref in "$skill_dir"references/*.md; do
    [ -e "$ref" ] || continue
    name="references/$(basename "$ref")"
    grep -rFq --include='*.md' "\`$name\`" "$skill_dir" --exclude="$(basename "$ref")" || {
      echo "$skill/$name is not named by any document in its skill" >&2
      exit 1
    }
  done
done
echo "Every shipped reference is named by some shipped file."

retired_names="$(sed '/^[[:space:]]*$/d' "$REPO_ROOT/core/scripts/RETIRED")"
retired_pattern="$(printf '%s\n' "$retired_names" | paste -sd'|' -)"
retired="$(rg -n "\\b(${retired_pattern})\\b" \
  "$TMP"/skills/varde-*/ --glob '*.md' --glob '*.json' --glob '*.sh' --glob '*.py' || true)"
if [ -n "$retired" ]; then
  echo "Active files name retired skills:" >&2
  printf '%s\n' "$retired" >&2
  exit 1
fi
echo "No active file names a retired skill."
