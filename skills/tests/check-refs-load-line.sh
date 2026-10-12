#!/usr/bin/env bash
# Fixture test for the pointer check in check-refs.sh.
#
# A `../<skill>/SKILL.md` load line is the one pointer allowed to leave its
# skill, and only to a skill the installed set contains and the citing skill
# declares in requires/recommends (or a self pointer, or a load marked
# conditional). This also pins that a broken backticked path fails, which the
# previous check missed because it scanned the temp root instead of the
# installed skills directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER="$SCRIPT_DIR/../check-refs.sh"
FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/check-refs-load-line.XXXXXX")"
trap 'rm -rf "$FIXTURE"' EXIT

skills="$FIXTURE/skills"

reset() {
  rm -rf "$skills"
  mkdir -p "$skills"
}

# make_skill <name> [<frontmatter relation line>...]
make_skill() {
  local name="$1"; shift
  mkdir -p "$skills/$name/references"
  {
    echo '---'
    echo "name: $name"
    printf '%s\n' "$@"
    echo '---'
    echo
    echo "# $name"
  } > "$skills/$name/SKILL.md"
}

pass() { # <case>
  if ! "$CHECKER" --check-pointers "$skills" >"$FIXTURE/out" 2>&1; then
    echo "FAIL: $1: valid pointer rejected" >&2
    cat "$FIXTURE/out" >&2
    exit 1
  fi
}

fails() { # <case> <expected substring>
  if "$CHECKER" --check-pointers "$skills" >"$FIXTURE/out" 2>&1; then
    echo "FAIL: $1: broken pointer accepted" >&2
    exit 1
  fi
  grep -Fq "$2" "$FIXTURE/out" || {
    echo "FAIL: $1: output did not name '$2'" >&2
    cat "$FIXTURE/out" >&2
    exit 1
  }
}

# A declared sibling skill loads with a pointer relative to SKILL.md.
reset
make_skill varde-citing 'recommends: [varde-target]'
make_skill varde-target
printf '%s\n' 'Load `varde-target`: read `../varde-target/SKILL.md`.' \
  >> "$skills/varde-citing/SKILL.md"
pass 'declared sibling load from SKILL.md'

# `requires` counts as a declaration too.
reset
make_skill varde-citing 'requires: [varde-target]'
make_skill varde-target
printf '%s\n' 'Load `varde-target`: read `../varde-target/SKILL.md`.' \
  >> "$skills/varde-citing/SKILL.md"
pass 'required sibling load from SKILL.md'

# The pointer at leaf depth is `../../`, and it is checked in a reference.
reset
make_skill varde-citing 'recommends: [varde-target]'
make_skill varde-target
printf '%s\n' 'Load `varde-target`: read `../../varde-target/SKILL.md`.' \
  > "$skills/varde-citing/references/leaf.md"
pass 'declared sibling load from a leaf reference'

# An undeclared sibling skill is an error.
reset
make_skill varde-citing
make_skill varde-target
printf '%s\n' 'Load `varde-target`: read `../varde-target/SKILL.md`.' \
  >> "$skills/varde-citing/SKILL.md"
fails 'undeclared sibling load' 'undeclared skill'

# A declared skill that is not installed is an error.
reset
make_skill varde-citing 'recommends: [varde-target]'
printf '%s\n' 'Load `varde-target`: read `../varde-target/SKILL.md`.' \
  >> "$skills/varde-citing/SKILL.md"
fails 'declared but missing sibling' 'resolves to no installed varde-target/SKILL.md'

# Wrong relative depth resolves to neither the citing skill nor the target.
reset
make_skill varde-citing 'recommends: [varde-target]'
make_skill varde-target
printf '%s\n' 'Load `varde-target`: read `../varde-target/SKILL.md`.' \
  > "$skills/varde-citing/references/leaf.md"
fails 'wrong ../ depth from a leaf' 'resolves to no installed varde-target/SKILL.md'

# A `../` pointer that leaves the skill for a non-SKILL file stays an error.
reset
make_skill varde-citing 'recommends: [varde-target]'
make_skill varde-target
printf '%s\n' '# other' > "$skills/varde-target/references/other.md"
printf '%s\n' 'See `../varde-target/references/other.md`.' \
  >> "$skills/varde-citing/SKILL.md"
fails 'non-SKILL sibling target' 'escapes the skill'

# The conditional marker is the accepted way to load an undeclared skill.
reset
make_skill varde-citing
make_skill varde-target
printf '%s\n' \
  '1. If `varde-target` is installed, read `../../varde-target/SKILL.md`.' \
  > "$skills/varde-citing/references/leaf.md"
pass 'conditional load of an undeclared skill'

# The conditional marker is also accepted behind a bullet list prefix.
reset
make_skill varde-citing
make_skill varde-target
printf '%s\n' \
  '- If `varde-target` is installed, read `../../varde-target/SKILL.md`.' \
  > "$skills/varde-citing/references/leaf.md"
pass 'conditional load behind a dash bullet'

reset
make_skill varde-citing
make_skill varde-target
printf '%s\n' \
  '* If `varde-target` is installed, read `../../varde-target/SKILL.md`.' \
  > "$skills/varde-citing/references/leaf.md"
pass 'conditional load behind a star bullet'

# The marker must open the sentence: a later mention does not qualify.
reset
make_skill varde-citing
make_skill varde-target
printf '%s\n' \
  'When present, if `varde-target` is installed, read `../../varde-target/SKILL.md`.' \
  > "$skills/varde-citing/references/leaf.md"
fails 'conditional marker must open the sentence' 'undeclared skill'

# A shared reference embedded in a skill may point at that skill itself.
reset
make_skill varde-self
printf '%s\n' 'Load `varde-self`: read `../../varde-self/SKILL.md`.' \
  > "$skills/varde-self/references/review-gates.md"
pass 'self pointer from an embedded shared reference'

# A backticked path that resolves to no installed file is an error.
reset
make_skill varde-citing
printf '%s\n' 'Read `references/missing.md` for details.' \
  >> "$skills/varde-citing/SKILL.md"
fails 'broken backticked path' 'varde-citing/SKILL.md -> references/missing.md'

echo 'check-refs load-line fixtures passed.'
