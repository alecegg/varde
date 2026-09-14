#!/usr/bin/env bash
# Guards the one reference invariant that install.sh can silently break: the
# canonical shared text lives in _shared/ at the repo root, which install.sh
# never copies (it installs one skill dir at a time). So any file that ships
# inside a skill must NOT point at `_shared/...` — that path won't exist on a
# user's machine. This is exactly the class of bug that let a
# `_shared/INTERVIEW.md` pointer ship inside a skill: the source tree has
# _shared/, so the reference "resolves" locally and only dangles post-install.
#
# Runs a throwaway install into a temp dir and scans the installed artifact, so
# it checks exactly what an end user receives. Exits non-zero if any installed
# file references _shared/.
#
# Scope note: this deliberately does NOT try to resolve every references/ or
# assets/ pointer. Skills intentionally cross-reference each other's docs (e.g.
# many name varde-worktree's `references/RESOLVE.md`), and one skill ships
# illustrative example paths — so a strict intra-package resolver produces
# permanent false positives. The _shared/ invariant is the precise, install-time
# regression that has zero legitimate exceptions.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

"$SCRIPT_DIR/install.sh" -f -d "$TMP" >/dev/null

if grep -rn "_shared/" "$TMP" >/dev/null 2>&1; then
  echo "Installed files reference _shared/, which install.sh does not copy:" >&2
  grep -rn "_shared/" "$TMP" | sed "s#$TMP/##" >&2
  echo "Fix: move the shared text into the skill (see sync-shared-refs.sh) and" >&2
  echo "point at references/<file> instead of _shared/<file>." >&2
  exit 1
fi
echo "No installed file references the un-installed _shared/ dir."
