#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER="$SCRIPT_DIR/../scripts/check-refs.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/repo"; B="$TMP/baselines"
mkdir -p "$R/m/src/p/skills/varde-x" "$R/m/src/p/how/varde-x" "$R/core" "$B/g1"
printf '%s\n' '# x' > "$R/m/src/p/skills/varde-x/SKILL.md"
printf '%s\n' 'topic' > "$R/m/src/p/how/varde-x/solo.md"
if "$CHECKER" --check-how "$R" >/dev/null 2>&1; then
  echo "orphan topic missing from core/how-unpointed.txt was accepted" >&2; exit 1
fi
printf '%s\n' 'how/varde-x/solo' > "$R/core/how-unpointed.txt"
"$CHECKER" --check-how "$R"
printf '%s\n' '{"step":"varde-x/solo","status":"retired"}' > "$B/g1/changelog.jsonl"
if "$CHECKER" --check-how "$R" "$B" >/dev/null 2>&1; then
  echo "retired topic id was accepted" >&2; exit 1
fi
echo "how orphan check allows listed topics and rejects the rest"
