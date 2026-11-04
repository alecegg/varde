#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER="$SCRIPT_DIR/../scripts/check-refs.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/repo/learn/ledgers" "$TMP/repo/src"
git -C "$TMP/repo" init -q
git -C "$TMP/repo" config user.email test@example.com
git -C "$TMP/repo" config user.name test
printf '%s\n' 'historic varde-'"change" > "$TMP/repo/learn/ledgers/history.json"
printf '%s\n' 'clean' > "$TMP/repo/src/current.md"
git -C "$TMP/repo" add .
"$CHECKER" --check-no-stale-skill "$TMP/repo"
printf '%s\n' 'stale varde-'"change" > "$TMP/repo/src/current.md"
git -C "$TMP/repo" add src/current.md
if "$CHECKER" --check-no-stale-skill "$TMP/repo" >/dev/null 2>&1; then
  echo "checker accepted a stale tracked reference" >&2
  exit 1
fi
echo "stale-skill check rejects tracked references and exempts learn ledgers"
