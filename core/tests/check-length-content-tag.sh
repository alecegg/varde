#!/usr/bin/env bash
set -euo pipefail

# varde learn check warns on a bare </content> line outside fenced code.

dir="$(mktemp -d "${TMPDIR:-/tmp}/content-tag.XXXXXX")"
trap 'rm -rf "$dir"' EXIT
VARDE=${VARDE_BIN:-$(git rev-parse --show-toplevel)/.venv/bin/varde}
export VARDE_CONFIG_DIR="$dir/config"

printf '# T\n\nText.\n  </content>\n\n```\n</content>\n```\n' >"$dir/bare.md"
out="$("$VARDE" learn check "$dir/bare.md")"
echo "$out" | grep -q "bare.md:4 (stray </content> line)" || { echo "FAIL: no warning on line 4"; echo "$out"; exit 1; }
[ "$(echo "$out" | grep -c 'stray </content>')" -eq 1 ] || { echo "FAIL: fenced line warned"; echo "$out"; exit 1; }
echo "ok"
