#!/usr/bin/env bash
# Guards the reference invariants that install.sh can silently break.
#
# Each skill is a SKILL.md over one flat references/ directory, and install.sh
# copies one skill dir at a time. So every pointer a shipped file names must
# resolve inside that same skill — a path that only resolves in the source tree
# dangles on a user's machine.
#
# Runs a throwaway install into a temp dir for the structural checks, so they
# see exactly what an end user receives.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/tests/storage-fallbacks.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/check-refs.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

"$SCRIPT_DIR/install.sh" -f -d "$TMP" >/dev/null

# First structural check: an installed skill is a SKILL.md over at most one
# level of references/, scripts/, and assets/. Check directories as well as
# files — a leftover empty directory tree is the visible shape of the layout
# even when nothing tracked lives in it, and a files-only check walks past it.
nested="$(find "$TMP"/varde-* -mindepth 2 -type d)"
if [ -n "$nested" ]; then
  echo "Installed skills contain a directory below the reference level:" >&2
  printf '%s\n' "$nested" | sed "s#$TMP/##" >&2
  exit 1
fi
if find "$TMP"/varde-* -mindepth 1 -maxdepth 1 -type d |
  grep -vE '/(references|scripts|assets)$' | grep -q .; then
  echo "Installed skills contain an unexpected top-level directory:" >&2
  find "$TMP"/varde-* -mindepth 1 -maxdepth 1 -type d |
    grep -vE '/(references|scripts|assets)$' | sed "s#$TMP/##" >&2
  exit 1
fi
echo "Every installed skill is a SKILL.md over one flat reference level."

# First invariant: every SKILL.md description must be a single-line scalar.
# A YAML folded scalar (`description: >`) is valid YAML, but some harnesses read
# frontmatter with a line-based regex instead of a YAML parser and end up
# showing the literal ">" as the entire description, so the skill reads as blank
# in the skill picker.
if grep -rn "^description: *[>|]" "$SCRIPT_DIR"/*/SKILL.md >/dev/null 2>&1; then
  echo "SKILL.md descriptions must be one single-line scalar:" >&2
  grep -rn "^description: *[>|]" "$SCRIPT_DIR"/*/SKILL.md | sed "s#$SCRIPT_DIR/##" >&2
  echo "Fix: collapse to one double-quoted line; lead with the user's outcome verbs and end \`Not for <nearest sibling task>\` when a sibling skill overlaps." >&2
  exit 1
fi
echo "All SKILL.md descriptions are single-line scalars."

# Second invariant: every backticked references//assets//scripts/ path inside a
# skill must resolve to a real file. A pointer is tried against each ancestor
# directory of the file holding it, so both mode-root-relative and
# skill-root-relative styles are accepted — but a path resolving nowhere is an
# instruction the agent cannot follow.
if ! python3 - "$TMP" <<'PYEOF'
import os, re, sys

root = sys.argv[1]
# Group 1 is the first whitespace-delimited token of the backtick span, so
# `scripts/x.sh <arg>` is checked as `scripts/x.sh`.
pattern = re.compile(r'`([^`\s]+)[^`\n]*`')
link_pattern = re.compile(r'\]\(([^)]+)\)')
cross_skill_re = re.compile(r'^varde-[a-z0-9-]+/')
broken = []

# Bare filenames that legitimately name something outside the skill.
EXTERNAL = {
    'SKILL.md', 'README.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
    'plan.md', 'index.md', 'log.md', 'review.md', 'handoff.md',
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


for skill in sorted(d for d in os.listdir(root) if d.startswith('varde-')):
    base = os.path.join(root, skill)
    if not os.path.isdir(base):
        continue
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
                # Must resolve to a real file without climbing above the
                # skill root — the installed skill is the whole world.
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
then
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
# file still names a retired skill — read from install.sh's RETIRED array
# rather than a second hardcoded list.
command -v rg >/dev/null 2>&1 || { echo "ripgrep (rg) is required" >&2; exit 1; }

for skill_dir in "$TMP"/varde-*/; do
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

retired_names="$(sed -n '/^RETIRED=(/,/^)/p' "$SCRIPT_DIR/install.sh" | grep -oE 'varde-[a-z-]+')"
retired_pattern="$(printf '%s\n' "$retired_names" | paste -sd'|' -)"
retired="$(rg -n "\\b(${retired_pattern})\\b" \
  "$TMP"/varde-*/ --glob '*.md' --glob '*.json' --glob '*.sh' --glob '*.py' || true)"
if [ -n "$retired" ]; then
  echo "Active files name retired skills:" >&2
  printf '%s\n' "$retired" >&2
  exit 1
fi
echo "No active file names a retired skill."
