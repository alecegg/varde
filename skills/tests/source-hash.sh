#!/usr/bin/env bash
set -euo pipefail

# source-hash.py must equal the old shell recipe for spec source_hash.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/../varde-docs/scripts/source-hash.py"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/source-hash.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
mkdir src
printf 'b\n' > src/b.txt
printf 'a\n' > 'src/a b.txt'
printf '\000\001\377bin' > src/c.bin
printf '*.txt text eol=crlf\n' > .gitattributes

expected=$(
  set -o pipefail
  printf '%s\n' src/b.txt 'src/a b.txt' src/c.bin | LC_ALL=C sort |
    while IFS= read -r src_path; do
      src_hash=$(git hash-object --no-filters -- "$src_path") || exit 1
      printf '%s%s' "$src_path" "$src_hash"
    done | git hash-object --stdin
)

actual=$(python3 "$SCRIPT" -- src/c.bin src/b.txt 'src/a b.txt')
[ "$actual" = "$expected" ] || { echo "FAIL: $actual != $expected" >&2; exit 1; }
if python3 "$SCRIPT" -- missing.txt 2>/dev/null; then
  echo "FAIL: missing file accepted" >&2
  exit 1
fi
echo "pass: source-hash"
