#!/usr/bin/env bash
# Guards the reference invariants that install.sh can silently break.
#
# Each skill is a SKILL.md over one flat references/ directory, and install.sh
# copies one skill dir at a time. So every pointer a shipped file names must
# resolve inside that same skill — a path that only resolves in the source tree
# dangles on a user's machine.
#
# The former `_shared/` invariant is retired along with the vendoring apparatus
# it guarded: there is no shared source left to point at.
#
# Runs a throwaway install into a temp dir for the structural checks, so they
# see exactly what an end user receives.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
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
  echo "SKILL.md descriptions must be one single-line double-quoted scalar:" >&2
  grep -rn "^description: *[>|]" "$SCRIPT_DIR"/*/SKILL.md | sed "s#$SCRIPT_DIR/##" >&2
  echo 'Fix: collapse to `description: "TRIGGER: ... SKIP: ... Example phrases: ..."`.' >&2
  exit 1
fi
echo "All SKILL.md descriptions are single-line scalars."

# Second invariant: every backticked references//assets//scripts/ path inside a
# skill must resolve to a real file. A pointer is tried against each ancestor
# directory of the file holding it, so both mode-root-relative and
# skill-root-relative styles are accepted — but a path resolving nowhere is an
# instruction the agent cannot follow.
if ! python3 - "$SCRIPT_DIR" <<'PYEOF'
import os, re, sys

root = sys.argv[1]
pattern = re.compile(r'`([A-Za-z0-9_./-]+\.(?:md|py|sh))`')
broken = []

# Bare filenames that legitimately name something outside the skill.
EXTERNAL = {
    'SKILL.md', 'README.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md',
    'plan.md', 'index.md', 'log.md', 'review.md', 'handoff.md',
    'logic.html', 'package.json', 'Makefile',
}

for skill in sorted(d for d in os.listdir(root) if d.startswith('varde-')):
    base = os.path.join(root, skill)
    if not os.path.isdir(base):
        continue
    files = {
        os.path.relpath(os.path.join(dirpath, name), base)
        for dirpath, _, names in os.walk(base)
        for name in names
        if name.endswith(('.md', '.sh', '.py'))
    }
    for rel in sorted(f for f in files if f.endswith('.md')):
        parts = rel.split('/')
        text = open(os.path.join(base, rel), errors='replace').read()
        basenames = {f.rsplit('/', 1)[-1] for f in files}
        for target in pattern.findall(text):
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

if broken:
    print("Backticked reference paths that resolve to no file:", file=sys.stderr)
    for entry in sorted(set(broken)):
        print("  " + entry, file=sys.stderr)
    print("Fix: point at the real file, or drop the backticks if the path is", file=sys.stderr)
    print("illustrative prose (e.g. naming another skill's internals).", file=sys.stderr)
    raise SystemExit(1)
PYEOF
then
  exit 1
fi
echo "All backticked reference paths resolve."
