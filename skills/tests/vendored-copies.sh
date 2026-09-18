#!/usr/bin/env bash
set -euo pipefail

# Vendored references are copied into each consuming skill on purpose — a skill
# that cannot be installed on its own is the bug that model avoids. The cost is
# that a fix lands in one copy and the siblings rot silently: commit 843ecba
# added a sandbox-retry rule to varde-code.md and reached only the review copy,
# leaving three skills falling straight back to Read/Grep on a denial one retry
# would have cleared.
#
# Most of each copy is meant to differ — every skill lists the operations it
# actually uses. What must not differ is the shared contract. This test names
# those sections explicitly rather than comparing every same-named heading,
# because some headings are legitimately tailored: varde-change's OCC section
# in varde-docs-cli.md covers `update` for plans while the docs/knowledge copies
# cover `update`/`set-field` over a bundle.
#
# Adding a section here is the way to say "this part is the contract, keep the
# copies in step."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# <reference filename>:<section>[,<section>...]
# `*` means the whole file must match byte for byte.
MANIFEST=(
  "worktree.md:*"
  "varde-code.md:__preamble__,Fallback rule"
  "varde-docs-cli.md:The OCC read-then-write contract,Output and exit codes,Fallback rule"
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
files = sorted(glob.glob(f"varde-*/references/{base}"))

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

if [ "$status" -ne 0 ]; then
  echo "FAIL: vendored copies drifted — apply the fix to every copy, not one." >&2
  exit 1
fi

echo "Vendored references agree on every shared contract section."
