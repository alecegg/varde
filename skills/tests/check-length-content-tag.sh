#!/usr/bin/env bash
set -euo pipefail

# check-length.py warns on a bare </content> line outside fenced code.

SKILLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dir="$(mktemp -d "${TMPDIR:-/tmp}/content-tag.XXXXXX")"
trap 'rm -rf "$dir"' EXIT

printf '# T\n\nText.\n  </content>\n\n```\n</content>\n```\n' >"$dir/bare.md"
out="$(python3 "$SKILLS_DIR/varde-agent-doc-authoring/scripts/check-length.py" "$dir/bare.md")"
echo "$out" | grep -q "bare.md:4 (stray </content> line)" || { echo "FAIL: no warning on line 4"; echo "$out"; exit 1; }
[ "$(echo "$out" | grep -c 'stray </content>')" -eq 1 ] || { echo "FAIL: fenced line warned"; echo "$out"; exit 1; }
echo "ok"
